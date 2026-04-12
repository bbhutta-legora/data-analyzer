# tests/test_chat.py
# Tests for chat prompt construction, response parsing, message building,
# and the /api/chat SSE endpoint.
# Related modules: backend/llm.py, backend/main.py
# PRD: #3 (Conversational Q&A)
#
# Confirmed behavior list (TEST-STRATEGY Steps 1–2):
#  1. build_chat_system_prompt includes column names from DataFrames
#  2. build_chat_system_prompt includes response format fields (code, explanation)
#  3. build_chat_system_prompt handles multiple DataFrames
#  4. build_chat_system_prompt instructs LLM to use dfs["name"] access pattern
#  5. build_chat_system_prompt includes sandbox library references
#  6. parse_chat_response extracts code and explanation from valid JSON
#  7. parse_chat_response extracts cleaning_suggestions when present
#  8. parse_chat_response defaults cleaning_suggestions when absent
#  9. parse_chat_response returns error for malformed JSON
# 10. parse_chat_response handles JSON wrapped in code fences
# 11. build_chat_messages with empty history returns only the new question
# 12. build_chat_messages with history includes history then new question
# 13. /api/chat returns SSE stream with explanation event
# 14. /api/chat returns SSE stream with result event
# 15. /api/chat returns SSE stream with done event
# 16. /api/chat returns cleaning_suggestions event when present
# 17. /api/chat returns error event when execution fails
# 18. /api/chat returns 404 for unknown session_id
# 19. /api/chat returns 400 for empty question
# 20. /api/chat updates session conversation_history after success
# 21. /api/chat updates session code_history after success

import json
from unittest.mock import patch

import pandas as pd

from llm import build_chat_messages, build_chat_system_prompt, parse_chat_response
from main import app, session_store

# TestClient import is deferred to after the llm imports so ImportErrors
# from missing llm functions surface clearly, separate from endpoint failures.
from fastapi.testclient import TestClient

client = TestClient(app)


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_dfs() -> dict[str, pd.DataFrame]:
    """Single-DataFrame dict — the common case (CSV upload)."""
    return {"data": pd.DataFrame({"revenue": [100, 200, 300], "cost": [50, 60, 70]})}


def parse_sse_events(response_text: str) -> list[dict]:
    """
    Parse SSE event stream text into a list of {event, data} dicts.

    Handles the standard SSE format:
        event: <type>
        data: <payload>
        <blank line>
    """
    events: list[dict] = []
    current_event: str | None = None
    current_data: list[str] = []

    for line in response_text.split("\n"):
        if line.startswith("event: "):
            # Flush previous event if one was accumulating
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

    # Flush trailing event if stream didn't end with a blank line
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


# Pre-built mock responses used across multiple endpoint tests.

MOCK_LLM_RESPONSE: str = json.dumps({
    "code": "print(dfs['data'].mean())",
    "explanation": "Calculating the mean of each column.",
})

MOCK_LLM_RESPONSE_WITH_CLEANING: str = json.dumps({
    "code": "print(dfs['data'].isnull().sum())",
    "explanation": "Checking missing values.",
    "cleaning_suggestions": [
        {"description": "Column revenue has 5% missing", "options": ["Drop rows", "Fill with median"]}
    ],
})

MOCK_EXECUTION_RESULT: dict = {
    "stdout": "revenue    200.0\ncost        60.0\ndtype: float64",
    "figures": [],
    "error": None,
    "dataframe_changed": False,
}


# ── System prompt construction ───────────────────────────────────────────────


def test_chat_system_prompt_includes_column_names():
    # Behavior 1: system prompt contains all column names from the DataFrame(s).
    # Why: without column names the LLM generates code referencing columns that don't exist.
    prompt = build_chat_system_prompt(make_dfs())
    assert "revenue" in prompt
    assert "cost" in prompt


def test_chat_system_prompt_includes_response_format_fields():
    # Behavior 2: system prompt tells the LLM to respond with code and explanation fields.
    # Why: without format instructions the LLM returns prose instead of parseable JSON.
    prompt = build_chat_system_prompt(make_dfs())
    assert "code" in prompt
    assert "explanation" in prompt


def test_chat_system_prompt_handles_multiple_dataframes():
    # Behavior 3: system prompt contains metadata for all DataFrames.
    # Why: Excel uploads produce multiple DataFrames; if only one is described, the LLM
    #      can't answer questions about the other sheets.
    dfs = {
        "Sales": pd.DataFrame({"revenue": [100]}),
        "Costs": pd.DataFrame({"amount": [50]}),
    }
    prompt = build_chat_system_prompt(dfs)
    assert "Sales" in prompt
    assert "Costs" in prompt
    assert "revenue" in prompt
    assert "amount" in prompt


def test_chat_system_prompt_instructs_dfs_access_pattern():
    # Behavior 4: system prompt tells the LLM to use dfs["name"] to access DataFrames.
    # Why: the executor namespace uses a dfs dict; if the LLM uses 'df' instead, every
    #      code execution fails with a NameError.
    prompt = build_chat_system_prompt(make_dfs())
    assert 'dfs["' in prompt or "dfs['" in prompt


def test_chat_system_prompt_includes_library_descriptions():
    # Behavior 5: system prompt mentions available sandbox libraries.
    # Why: the LLM needs to know what's available so it doesn't generate code using
    #      unavailable libraries like requests or scipy.
    prompt = build_chat_system_prompt(make_dfs())
    assert "pandas" in prompt.lower()
    assert "matplotlib" in prompt.lower() or "plt" in prompt


# ── Response parsing ─────────────────────────────────────────────────────────


def test_parse_chat_response_extracts_code_and_explanation():
    # Behavior 6: valid JSON with code and explanation is correctly extracted.
    # Why: these feed directly into the executor and frontend display.
    raw = '{"code": "print(df.mean())", "explanation": "Calculating column means."}'
    parsed = parse_chat_response(raw)
    assert parsed["code"] == "print(df.mean())"
    assert parsed["explanation"] == "Calculating column means."


def test_parse_chat_response_extracts_cleaning_suggestions():
    # Behavior 7: cleaning_suggestions are extracted when present.
    # Why: dropping them silently means the user misses data quality issues.
    raw = json.dumps({
        "code": "print(1)",
        "explanation": "test",
        "cleaning_suggestions": [
            {"description": "Column age has 10% missing", "options": ["Drop", "Fill median"]}
        ],
    })
    parsed = parse_chat_response(raw)
    assert len(parsed["cleaning_suggestions"]) == 1
    assert parsed["cleaning_suggestions"][0]["description"] == "Column age has 10% missing"


def test_parse_chat_response_defaults_cleaning_suggestions_when_absent():
    # Behavior 8: missing cleaning_suggestions defaults to empty array.
    # Why: the LLM may omit this for clean datasets; crashing on a missing key breaks
    #      every Q&A exchange.
    raw = '{"code": "x=1", "explanation": "test"}'
    parsed = parse_chat_response(raw)
    assert parsed["cleaning_suggestions"] == []


def test_parse_chat_response_returns_error_for_malformed_json():
    # Behavior 9: non-JSON input returns a dict with an "error" key.
    # Why: if the LLM returns prose, we need a structured error rather than an
    #      unhandled exception surfacing as a 500.
    parsed = parse_chat_response("this is not json at all")
    assert "error" in parsed


def test_parse_chat_response_handles_code_fenced_json():
    # Behavior 10: JSON wrapped in code fences is parsed correctly after stripping.
    # Why: LLMs wrap JSON ~40% of the time; without stripping, json.loads fails.
    raw = '```json\n{"code": "print(1)", "explanation": "Fenced."}\n```'
    parsed = parse_chat_response(raw)
    assert parsed["code"] == "print(1)"
    assert parsed["explanation"] == "Fenced."


# ── Message building ─────────────────────────────────────────────────────────


def test_build_chat_messages_with_empty_history():
    # Behavior 11: with no history, messages contain only the new user question.
    # Why: the first question has no prior context; the message list must be valid.
    messages = build_chat_messages("What is the mean?", [])
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "What is the mean?"


def test_build_chat_messages_with_history():
    # Behavior 12: history entries appear before the new question.
    # Why: without prior context, the LLM can't handle follow-up questions.
    history = [
        {"role": "user", "content": "previous question"},
        {"role": "assistant", "content": "previous answer"},
    ]
    messages = build_chat_messages("follow up question", history)
    assert len(messages) == 3
    assert messages[0] == history[0]
    assert messages[1] == history[1]
    assert messages[2]["role"] == "user"
    assert messages[2]["content"] == "follow up question"


# ── SSE endpoint — happy path ────────────────────────────────────────────────


def test_chat_endpoint_returns_sse_stream_with_explanation():
    # Behavior 13: the SSE stream contains an explanation event with the LLM's text.
    # Why: the explanation is the primary user-facing output.
    session_id = create_session_with_data()

    with patch("main.call_llm_chat", return_value=MOCK_LLM_RESPONSE), \
         patch("main.execute_code", return_value=MOCK_EXECUTION_RESULT):
        response = client.post("/api/chat", json={
            "session_id": session_id,
            "question": "What is the mean of each column?",
        })

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    events = parse_sse_events(response.text)
    explanation_events = [e for e in events if e["event"] == "explanation"]
    assert len(explanation_events) >= 1
    assert "Calculating the mean" in explanation_events[0]["data"]


def test_chat_endpoint_returns_sse_stream_with_result():
    # Behavior 14: the SSE stream contains a result event with execution output.
    # Why: execution results (charts, data) are what the user asked for.
    session_id = create_session_with_data()

    with patch("main.call_llm_chat", return_value=MOCK_LLM_RESPONSE), \
         patch("main.execute_code", return_value=MOCK_EXECUTION_RESULT):
        response = client.post("/api/chat", json={
            "session_id": session_id,
            "question": "What is the mean?",
        })

    events = parse_sse_events(response.text)
    result_events = [e for e in events if e["event"] == "result"]
    assert len(result_events) == 1
    result_data = json.loads(result_events[0]["data"])
    assert "stdout" in result_data
    assert "figures" in result_data


def test_chat_endpoint_returns_sse_stream_with_done():
    # Behavior 15: the SSE stream ends with a done event.
    # Why: the frontend needs to know when to stop listening.
    session_id = create_session_with_data()

    with patch("main.call_llm_chat", return_value=MOCK_LLM_RESPONSE), \
         patch("main.execute_code", return_value=MOCK_EXECUTION_RESULT):
        response = client.post("/api/chat", json={
            "session_id": session_id,
            "question": "What is the mean?",
        })

    events = parse_sse_events(response.text)
    assert events[-1]["event"] == "done"


def test_chat_endpoint_streams_cleaning_suggestions_when_present():
    # Behavior 16: when the LLM response includes cleaning_suggestions, a
    #              cleaning_suggestions SSE event is emitted.
    # Why: cleaning suggestions trigger interactive UI cards.
    session_id = create_session_with_data()

    with patch("main.call_llm_chat", return_value=MOCK_LLM_RESPONSE_WITH_CLEANING), \
         patch("main.execute_code", return_value=MOCK_EXECUTION_RESULT):
        response = client.post("/api/chat", json={
            "session_id": session_id,
            "question": "Check data quality",
        })

    events = parse_sse_events(response.text)
    cleaning_events = [e for e in events if e["event"] == "cleaning_suggestions"]
    assert len(cleaning_events) == 1
    suggestions = json.loads(cleaning_events[0]["data"])
    assert len(suggestions) >= 1


# ── SSE endpoint — error handling ────────────────────────────────────────────


def test_chat_endpoint_returns_404_for_unknown_session():
    # Behavior 18: unknown session_id returns 404.
    # Why: a clear 404 tells the frontend the session expired.
    response = client.post("/api/chat", json={
        "session_id": "nonexistent-session-id",
        "question": "What is the mean?",
    })
    assert response.status_code == 404


def test_chat_endpoint_returns_400_for_empty_question():
    # Behavior 19: empty question returns 400.
    # Why: sending an empty question wastes an LLM API call.
    session_id = create_session_with_data()
    response = client.post("/api/chat", json={
        "session_id": session_id,
        "question": "",
    })
    assert response.status_code == 400


def test_chat_endpoint_streams_error_on_execution_failure():
    # Behavior 17: when code execution fails on BOTH attempts (original + retry),
    # the stream contains an error event.
    # Why: the user needs to know their question couldn't be answered.
    # Updated for Step 11: a single failure triggers a retry, so both attempts
    # must fail for the error event to be emitted.
    session_id = create_session_with_data()

    failed_execution: dict = {
        "stdout": "",
        "figures": [],
        "error": "NameError: name 'undefined_var' is not defined",
        "dataframe_changed": False,
    }

    with patch("main.call_llm_chat", return_value=MOCK_LLM_RESPONSE), \
         patch("main.execute_code", return_value=failed_execution):
        response = client.post("/api/chat", json={
            "session_id": session_id,
            "question": "Use undefined_var",
        })

    events = parse_sse_events(response.text)
    error_events = [e for e in events if e["event"] == "error"]
    assert len(error_events) >= 1


# ── Session state updates ────────────────────────────────────────────────────


def test_chat_endpoint_updates_conversation_history():
    # Behavior 20: after success, the session's conversation_history contains
    #              the user question and the assistant's explanation.
    # Why: without history updates, follow-up questions have no context.
    session_id = create_session_with_data()

    with patch("main.call_llm_chat", return_value=MOCK_LLM_RESPONSE), \
         patch("main.execute_code", return_value=MOCK_EXECUTION_RESULT):
        client.post("/api/chat", json={
            "session_id": session_id,
            "question": "What is the mean?",
        })

    session = session_store.get(session_id)
    assert len(session.conversation_history) >= 2
    assert session.conversation_history[0]["role"] == "user"
    assert "mean" in session.conversation_history[0]["content"]
    assert session.conversation_history[1]["role"] == "assistant"


def test_chat_endpoint_updates_code_history():
    # Behavior 21: after success, the session's code_history contains the code
    #              and explanation from the LLM response.
    # Why: code_history feeds notebook export.
    session_id = create_session_with_data()

    with patch("main.call_llm_chat", return_value=MOCK_LLM_RESPONSE), \
         patch("main.execute_code", return_value=MOCK_EXECUTION_RESULT):
        client.post("/api/chat", json={
            "session_id": session_id,
            "question": "What is the mean?",
        })

    session = session_store.get(session_id)
    assert len(session.code_history) >= 1
    assert "code" in session.code_history[0]
    assert "explanation" in session.code_history[0]
