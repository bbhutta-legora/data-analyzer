# tests/test_error_recovery.py
# Tests for Step 11: Error Recovery (automatic retry on chat failures).
# Related modules: backend/main.py (retry loop), backend/llm.py (build_retry_messages)
# PRD: #6 (Error Recovery)
#
# Confirmed behavior list:
#  1. Execution error on first attempt triggers retry with error context
#  2. Retry succeeds after first execution error → user sees successful result
#  3. Both attempts fail → user sees friendly error message
#  4. LLM API error on first attempt triggers retry
#  5. JSON parse error on first attempt triggers retry
#  6. Timeout error on first attempt triggers retry with "simpler code" guidance
#  7. Only the final outcome is stored in conversation_history (not intermediate failures)
#  8. build_retry_messages includes original question, failed code, and error traceback
#  9. build_retry_messages includes timeout guidance when error contains "timed out"

import json
from unittest.mock import patch

import pandas as pd

from llm import build_retry_messages
from main import app, session_store

from fastapi.testclient import TestClient

client = TestClient(app)


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_dfs() -> dict[str, pd.DataFrame]:
    """Single-DataFrame dict — the common case (CSV upload)."""
    return {"data": pd.DataFrame({"revenue": [100, 200, 300], "cost": [50, 60, 70]})}


def parse_sse_events(response_text: str) -> list[dict]:
    """Parse SSE event stream text into a list of {event, data} dicts."""
    events: list[dict] = []
    current_event: str | None = None
    current_data: list[str] = []

    for line in response_text.split("\n"):
        if line.startswith("event: "):
            if current_event is not None:
                events.append({
                    "event": current_event,
                    "data": "\n".join(current_data),
                })
            current_event = line[len("event: "):]
            current_data = []
        elif line.startswith("data: "):
            current_data.append(line[len("data: "):])
        elif line == "" and current_event is not None:
            events.append({
                "event": current_event,
                "data": "\n".join(current_data),
            })
            current_event = None
            current_data = []

    if current_event is not None:
        events.append({
            "event": current_event,
            "data": "\n".join(current_data),
        })

    return events


def create_session_with_data(
    dfs: dict[str, pd.DataFrame] | None = None,
    api_key: str = "sk-test",
    provider: str = "openai",
    model: str = "gpt-5.4-mini",
) -> str:
    """Create a session in the shared store and return its session_id."""
    if dfs is None:
        dfs = make_dfs()
    return session_store.create(dfs, api_key=api_key, provider=provider, model=model)


# Mock LLM responses
MOCK_LLM_RESPONSE_GOOD = json.dumps({
    "code": "print(dfs['data'].mean())",
    "explanation": "Calculating the mean of each column.",
})

MOCK_LLM_RESPONSE_FIXED = json.dumps({
    "code": "print(dfs['data'].describe())",
    "explanation": "Describing the dataset statistics.",
})

MOCK_EXECUTION_SUCCESS = {
    "stdout": "revenue    200.0\ncost        60.0\ndtype: float64",
    "figures": [],
    "error": None,
    "dataframe_changed": False,
}

MOCK_EXECUTION_FAILURE = {
    "stdout": "",
    "figures": [],
    "error": "NameError: name 'undefined_var' is not defined",
    "dataframe_changed": False,
}

MOCK_EXECUTION_TIMEOUT = {
    "stdout": "",
    "figures": [],
    "error": "Code execution timed out",
    "dataframe_changed": False,
}


# ── Execution error retry ───────────────────────────────────────────────────


def test_retry_succeeds_after_execution_error():
    # Behavior 1-2: first execution fails, retry LLM call produces fixed code
    # that executes successfully → user sees result, not error.
    session_id = create_session_with_data()

    call_count = {"n": 0}

    def mock_call_llm_chat(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return MOCK_LLM_RESPONSE_GOOD
        return MOCK_LLM_RESPONSE_FIXED

    exec_count = {"n": 0}

    def mock_execute_code(*args, **kwargs):
        exec_count["n"] += 1
        if exec_count["n"] == 1:
            return MOCK_EXECUTION_FAILURE
        return MOCK_EXECUTION_SUCCESS

    with patch("main.call_llm_chat", side_effect=mock_call_llm_chat), \
         patch("main.execute_code", side_effect=mock_execute_code):
        response = client.post("/api/chat", json={
            "session_id": session_id,
            "question": "What is the mean?",
        })

    events = parse_sse_events(response.text)
    error_events = [e for e in events if e["event"] == "error"]
    result_events = [e for e in events if e["event"] == "result"]

    assert len(error_events) == 0, "No error should reach the user when retry succeeds"
    assert len(result_events) == 1, "A successful result should be emitted"
    assert call_count["n"] == 2, "LLM should be called twice (original + retry)"


def test_both_attempts_fail_returns_friendly_error():
    # Behavior 3: both original and retry execution fail → user sees error.
    session_id = create_session_with_data()

    with patch("main.call_llm_chat", return_value=MOCK_LLM_RESPONSE_GOOD), \
         patch("main.execute_code", return_value=MOCK_EXECUTION_FAILURE):
        response = client.post("/api/chat", json={
            "session_id": session_id,
            "question": "Use undefined_var",
        })

    events = parse_sse_events(response.text)
    error_events = [e for e in events if e["event"] == "error"]

    assert len(error_events) >= 1, "Error event should be emitted after both attempts fail"


# ── LLM API error retry ─────────────────────────────────────────────────────


def test_retry_succeeds_after_llm_api_error():
    # Behavior 4: LLM API error on first call, succeeds on retry.
    session_id = create_session_with_data()

    call_count = {"n": 0}

    def mock_call_llm_chat(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("API rate limit exceeded")
        return MOCK_LLM_RESPONSE_GOOD

    with patch("main.call_llm_chat", side_effect=mock_call_llm_chat), \
         patch("main.execute_code", return_value=MOCK_EXECUTION_SUCCESS):
        response = client.post("/api/chat", json={
            "session_id": session_id,
            "question": "What is the mean?",
        })

    events = parse_sse_events(response.text)
    error_events = [e for e in events if e["event"] == "error"]
    result_events = [e for e in events if e["event"] == "result"]

    assert len(error_events) == 0, "No error when retry succeeds"
    assert len(result_events) == 1, "Result should be emitted after successful retry"
    assert call_count["n"] == 2, "LLM called twice"


# ── JSON parse error retry ───────────────────────────────────────────────────


def test_retry_succeeds_after_json_parse_error():
    # Behavior 5: LLM returns invalid JSON first, valid JSON on retry.
    session_id = create_session_with_data()

    call_count = {"n": 0}

    def mock_call_llm_chat(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return "This is not valid JSON at all"
        return MOCK_LLM_RESPONSE_GOOD

    with patch("main.call_llm_chat", side_effect=mock_call_llm_chat), \
         patch("main.execute_code", return_value=MOCK_EXECUTION_SUCCESS):
        response = client.post("/api/chat", json={
            "session_id": session_id,
            "question": "What is the mean?",
        })

    events = parse_sse_events(response.text)
    error_events = [e for e in events if e["event"] == "error"]
    result_events = [e for e in events if e["event"] == "result"]

    assert len(error_events) == 0, "No error when retry succeeds"
    assert len(result_events) == 1, "Result should be emitted after successful retry"
    assert call_count["n"] == 2, "LLM called twice"


# ── Timeout error retry ─────────────────────────────────────────────────────


def test_retry_succeeds_after_timeout_error():
    # Behavior 6: execution times out first, retry produces faster code that succeeds.
    session_id = create_session_with_data()

    call_count = {"n": 0}

    def mock_call_llm_chat(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return MOCK_LLM_RESPONSE_GOOD
        return MOCK_LLM_RESPONSE_FIXED

    exec_count = {"n": 0}

    def mock_execute_code(*args, **kwargs):
        exec_count["n"] += 1
        if exec_count["n"] == 1:
            return MOCK_EXECUTION_TIMEOUT
        return MOCK_EXECUTION_SUCCESS

    with patch("main.call_llm_chat", side_effect=mock_call_llm_chat), \
         patch("main.execute_code", side_effect=mock_execute_code):
        response = client.post("/api/chat", json={
            "session_id": session_id,
            "question": "Compute statistics",
        })

    events = parse_sse_events(response.text)
    error_events = [e for e in events if e["event"] == "error"]
    result_events = [e for e in events if e["event"] == "result"]

    assert len(error_events) == 0, "No error when retry succeeds"
    assert len(result_events) == 1
    assert call_count["n"] == 2


# ── Conversation history: only final outcome ─────────────────────────────────


def test_only_final_outcome_in_conversation_history():
    # Behavior 7: after a retry that succeeds, conversation_history contains
    # only the final successful exchange — not the intermediate failure.
    session_id = create_session_with_data()

    call_count = {"n": 0}

    def mock_call_llm_chat(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return MOCK_LLM_RESPONSE_GOOD
        return MOCK_LLM_RESPONSE_FIXED

    exec_count = {"n": 0}

    def mock_execute_code(*args, **kwargs):
        exec_count["n"] += 1
        if exec_count["n"] == 1:
            return MOCK_EXECUTION_FAILURE
        return MOCK_EXECUTION_SUCCESS

    with patch("main.call_llm_chat", side_effect=mock_call_llm_chat), \
         patch("main.execute_code", side_effect=mock_execute_code):
        client.post("/api/chat", json={
            "session_id": session_id,
            "question": "What is the mean?",
        })

    session = session_store.get(session_id)
    # Should have exactly 2 entries: user question + assistant response
    assert len(session.conversation_history) == 2
    assert session.conversation_history[0]["role"] == "user"
    assert session.conversation_history[1]["role"] == "assistant"
    # The assistant content should be from the retry response, not the first attempt
    assert session.conversation_history[1]["content"] == "Describing the dataset statistics."


# ── Pure function: build_retry_messages ──────────────────────────────────────


def test_build_retry_messages_includes_error_context():
    # Behavior 8: retry messages include the original question, failed code,
    # and the error traceback so the LLM can fix the code.
    messages = build_retry_messages(
        original_question="What is the mean?",
        failed_code="print(undefined_var)",
        error_traceback="NameError: name 'undefined_var' is not defined",
        conversation_history=[],
    )

    # Should return a list of message dicts
    assert isinstance(messages, list)
    assert len(messages) >= 1

    # The last message should contain the error context
    last_content = messages[-1]["content"]
    assert "undefined_var" in last_content
    assert "NameError" in last_content
    assert "What is the mean?" in last_content


def test_build_retry_messages_includes_timeout_guidance():
    # Behavior 9: when the error is a timeout, the retry message asks for
    # simpler, faster code.
    messages = build_retry_messages(
        original_question="Run complex analysis",
        failed_code="import time; time.sleep(999)",
        error_traceback="Code execution timed out",
        conversation_history=[],
    )

    last_content = messages[-1]["content"]
    assert "simpler" in last_content.lower() or "faster" in last_content.lower()
