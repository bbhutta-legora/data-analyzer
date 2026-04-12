# Execution Plan: Step 11 — Error Recovery

## 1. What we're building

Step 11 adds automatic retry when LLM-generated code fails to execute. When the sandbox returns an execution error, the system re-prompts the LLM with the original code, the error traceback, and the original question, giving it one chance to produce corrected code. If the retry also fails, the user sees a plain-English error explanation and a suggestion to rephrase. The frontend is updated to display a friendlier error message. Maximum retry count is 1 (original attempt + 1 retry). PRD ref: #6 (Error Recovery).

## 2. Current state

### Backend: `main.py` — `/api/chat` event_generator (lines 397-464)

The current chat flow is strictly single-attempt:
1. Build system prompt and messages (lines 398-402)
2. Call `call_llm_chat` (lines 410-412) — catches LLM API errors and yields an SSE `error` event
3. Parse the response with `parse_chat_response` (line 419) — yields SSE `error` on parse failure
4. If parsed response contains code, call `execute_code` (line 430)
5. If `exec_result["error"]` is truthy (line 432), yield SSE `error` event with the raw traceback and stop — **no retry**
6. Otherwise yield SSE `result` with stdout/figures
7. Append to `conversation_history` and `code_history` (lines 447-460)
8. Yield SSE `done`

The retry logic needs to intercept at three failure points: step 2 (LLM API errors), step 3 (JSON parse failures), and step 5 (execution errors/timeouts). Instead of immediately yielding an error to the frontend, re-prompt the LLM and try again.

### Backend: `llm.py` — LLM call functions

- `call_llm_chat(system_prompt, messages, api_key, provider, model)` (line 389): sends multi-turn chat request, returns raw string. Dispatches to OpenAI or Anthropic.
- `parse_chat_response(raw)` (line 226): strips code fences, JSON-parses, returns `{code, explanation, cleaning_suggestions}` or `{error}`.
- `build_chat_messages(question, conversation_history)` (line 209): appends user question to history, returns new list.
- There is no retry-aware function or error-context prompt construction currently.

### Backend: `executor.py` — `execute_code` (line 197)

- Returns `dict` with keys: `stdout`, `figures`, `error`, `dataframe_changed`.
- `error` is `None` on success or a traceback string on failure.
- Error string contains the full Python traceback (e.g., `NameError: name 'x' is not defined`).

### Frontend: `MessageBubble.tsx` (lines 61-75)

- Error display: if `message.error` is truthy, renders a red-tinted box with the raw error string.
- No "retry" indicator, no friendly rephrasing suggestion — just the raw error text.

### Frontend: `api.ts` — SSE client (lines 229-245)

- Handles event types: `explanation`, `result`, `cleaning_suggestions`, `error`, `done`.
- `error` events call `callbacks.onError(data)` where `data` is the raw string.
- No `retrying` event type exists.

### Frontend: `store.ts` — Message type (lines 51-59)

- `Message.error` is `string | undefined`.
- `updateLastAssistantMessage` merges partial fields into the last assistant message.

### Frontend: `ChatPanel.tsx` — `sendQuestion` (lines 119-154)

- Creates user message + placeholder assistant message, then streams SSE events.
- `onError` callback stores the error string on the assistant message.
- No retry-awareness.

### Existing tests: `backend/tests/test_chat.py`

- `test_chat_endpoint_streams_error_on_execution_failure` (line 365): mocks `execute_code` to return an error, asserts an SSE `error` event is emitted. This test will need updating — after Step 11, a single execution failure triggers a retry, not an immediate error.

## 3. Execution sequence

| Phase | Name | What happens |
|-------|------|-------------|
| A | Test spec | Present behaviors and test cases for error recovery to the user for review. Cover: retry on first failure (all error types), success after retry, double failure returns friendly error, retry prompt includes error context, timeout retry asks for simpler code, frontend friendly error with collapsible detail. Wait for confirmation. |
| B | Tests | Write `backend/tests/test_error_recovery.py` and any frontend test updates. Run them, confirm all fail for the right reasons. |
| C | Implementation | Add retry logic to `main.py`'s `event_generator` (or extract into a helper in `llm.py`). Add `build_retry_messages()` to `llm.py`. Update `MessageBubble.tsx` for friendly error text. Optionally add a `retrying` SSE event type. |
| D | Verification | Break-the-implementation check: disable the retry path and verify the retry-specific tests fail while existing tests still pass. Self-audit summary. Present for user confirmation. |
| E | Code review | Scan all changed files against `harness/code_review_patterns.md`. Fix violations, re-run tests. |
| F | Reflection | Follow `harness/reflection.md` — capture learnings, propose harness updates if warranted. |

No Phase A0 (wireframes) is needed. The frontend change is purely behavioral — adding a friendly message string to the existing error box in `MessageBubble.tsx`. There is no new layout, component, or interaction pattern.

## 4. Implementation approach

### Files to modify

1. **`backend/main.py`** — modify `event_generator` in the `/api/chat` endpoint:
   - Wrap the LLM call → parse → execute sequence in a retry loop (max 1 retry).
   - On any failure (LLM API error, JSON parse error, execution error, or timeout), build retry messages with error context and try again.
   - For timeout retries, include guidance in the retry prompt to generate simpler/faster code.
   - If retry succeeds, yield `explanation` (updated) + `result` as normal.
   - If retry fails, yield `error` with a friendly message.
   - Update `conversation_history` and `code_history` to reflect the final outcome only (not intermediate failures).

2. **`backend/llm.py`** — add a pure function for building the retry prompt:
   - `build_retry_messages(original_question, failed_code, error_traceback, conversation_history)` — returns a messages list where the last user message includes the original question, the code that failed, and the error traceback, instructing the LLM to fix the code.
   - This keeps the retry prompt construction testable independently of I/O.

3. **`backend/tests/test_error_recovery.py`** — new test file covering retry behaviors.

4. **`backend/tests/test_chat.py`** — update `test_chat_endpoint_streams_error_on_execution_failure` (line 365). After Step 11, a single execution failure triggers a retry. The test must mock both the first and retry LLM calls. Alternatively, the existing test can mock both attempts to fail so it still expects an error event.

5. **`frontend/src/components/MessageBubble.tsx`** — update the error display:
   - When `message.error` is present, show a friendly wrapper message like "I couldn't execute the analysis. Try rephrasing your question or being more specific."
   - Add a collapsible "Show details" toggle for the raw traceback, matching the existing "Show code" pattern.

### Function decomposition

- **Pure function (testable without mocks):** `build_retry_messages(original_question, failed_code, error_traceback, conversation_history)` in `llm.py`. Constructs the messages array for the retry LLM call. The retry message should say something like: "The following code failed with an error. Please fix the code and try again.\n\nOriginal code:\n```\n{code}\n```\n\nError:\n```\n{traceback}\n```"
- **I/O logic (in event_generator):** The retry orchestration stays in `main.py`'s `event_generator` since it needs access to session state, SSE yielding, and the execute_code call. This avoids the implementation plan's suggestion of a `generate_chat_response_with_retry()` in `llm.py` that would couple LLM calls with code execution — keeping them separate preserves the current clean I/O boundary.

### Key design decisions

1. **Retry count: 1** — the implementation plan specifies "Maximum retry count is 1 (original + 1 retry)." This is hardcoded as a constant `MAX_CODE_RETRIES = 1` in `main.py`.

2. **Retry scope: all error types** — all failures get one retry: execution errors (`exec_result["error"]`), LLM API errors (network, auth, rate limit), JSON parse errors, and execution timeouts. Transient network issues may resolve on a second attempt, non-deterministic LLM output may produce valid JSON on retry, and timeouts may benefit from a retry prompt that asks for simpler code.

3. **Retry stays in `event_generator`, not in `llm.py`** — the implementation plan suggests a `generate_chat_response_with_retry()` in `llm.py` that wraps LLM call + execution. This would mean `llm.py` imports and calls `execute_code`, breaking the current clean separation where `llm.py` handles prompt construction and LLM calls while `main.py` orchestrates execution. The retry loop belongs in `event_generator` where both the LLM call and execution already live.

4. **Conversation history: only the final result is appended** — intermediate failed attempts are NOT added to `conversation_history`. The retry context (failed code + error) is passed as part of the messages for the retry call but is not persisted. This keeps the conversation history clean for future turns.

5. **Code history: record the successful attempt** — `code_history` records the code that ultimately succeeded (or the last failed code if both attempts fail).

## 5. Deviations from the implementation plan

### Deviation 1: No `generate_chat_response_with_retry()` in `llm.py`

The implementation plan proposes adding `generate_chat_response_with_retry()` to `llm.py` that wraps the full chat flow (LLM call -> execute -> retry). The test examples in the plan mock both `llm.call_llm` and `llm.execute_code`, implying this function lives in `llm.py` and calls the executor.

**Problem:** This would mean `llm.py` imports `executor.py`, breaking the current architecture where `llm.py` is a pure prompt/parse module and `main.py` is the orchestrator. It also makes `llm.py` harder to test — currently all its functions are either pure or thin I/O wrappers.

**Instead:** The retry loop will live in `main.py`'s `event_generator`. A new pure function `build_retry_messages()` will be added to `llm.py` for constructing the retry prompt. Tests will either test the endpoint integration (via TestClient, like existing `test_chat.py`) or test `build_retry_messages()` as a pure function.

### Deviation 2: Test structure

The implementation plan shows `async` tests using `pytest.mark.asyncio`. The current codebase uses synchronous FastAPI handlers (not async) and synchronous test functions with `TestClient`. The error recovery tests will follow the existing synchronous pattern for consistency.

### Deviation 3: Tests mock at the `main` module boundary, not `llm`

The existing `test_chat.py` patches `main.call_llm_chat` and `main.execute_code` — i.e., the imports as seen from `main.py`. The error recovery tests will follow this same pattern rather than patching `llm.call_llm` and `llm.execute_code` as the plan suggests.

---

## Resolved decisions

1. **Silent retry** — no new SSE event type. The backend retries invisibly. The user either sees a successful result (if retry works) or a friendly error (if both fail).

2. **All error types are retryable** — execution errors, LLM API failures (network, auth, rate limit), JSON parse errors, and execution timeouts all get one retry. For timeouts, the retry prompt should ask the LLM to generate simpler/faster code.

3. **Only the final outcome goes into conversation_history** — intermediate failed attempts are ephemeral (included in the retry LLM call's messages but not persisted).

4. **Friendly error wrapper + collapsible technical detail** — matches the existing "Show code" toggle pattern in `MessageBubble.tsx`.

5. **Update existing test** — `test_chat_endpoint_streams_error_on_execution_failure` must be updated to mock two failed attempts (original + retry) so it still expects the error event after exhausting retries.
