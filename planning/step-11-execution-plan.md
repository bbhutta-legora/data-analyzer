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

The retry logic needs to intercept at step 5: when `exec_result["error"]` is truthy, instead of immediately yielding an error to the frontend, re-prompt the LLM with error context and try again.

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
| A | Test spec | Present behaviors and test cases for error recovery to the user for review. Cover: retry on first failure, success after retry, double failure returns friendly error, retry prompt includes error context, retryable vs. non-retryable errors, SSE "retrying" event (if adopted), frontend friendly error display. Wait for confirmation. |
| B | Tests | Write `backend/tests/test_error_recovery.py` and any frontend test updates. Run them, confirm all fail for the right reasons. |
| C | Implementation | Add retry logic to `main.py`'s `event_generator` (or extract into a helper in `llm.py`). Add `build_retry_messages()` to `llm.py`. Update `MessageBubble.tsx` for friendly error text. Optionally add a `retrying` SSE event type. |
| D | Verification | Break-the-implementation check: disable the retry path and verify the retry-specific tests fail while existing tests still pass. Self-audit summary. Present for user confirmation. |
| E | Code review | Scan all changed files against `harness/code_review_patterns.md`. Fix violations, re-run tests. |
| F | Reflection | Follow `harness/reflection.md` — capture learnings, propose harness updates if warranted. |

No Phase A0 (wireframes) is needed. The frontend change is purely behavioral — adding a friendly message string to the existing error box in `MessageBubble.tsx`. There is no new layout, component, or interaction pattern.

## 4. Implementation approach

### Files to modify

1. **`backend/main.py`** — modify `event_generator` in the `/api/chat` endpoint:
   - After `execute_code` returns an error, instead of immediately yielding an SSE `error`, enter the retry path.
   - Optionally yield an SSE `retrying` event so the frontend can show "Retrying..." (see open question below).
   - Build retry messages that include the failed code and traceback, call `call_llm_chat` again, parse, execute again.
   - If retry succeeds, yield `explanation` (updated) + `result` as normal.
   - If retry fails, yield `error` with a friendly message.
   - Update `conversation_history` and `code_history` to reflect the final outcome (not intermediate failures).

2. **`backend/llm.py`** — add a pure function for building the retry prompt:
   - `build_retry_messages(original_question, failed_code, error_traceback, conversation_history)` — returns a messages list where the last user message includes the original question, the code that failed, and the error traceback, instructing the LLM to fix the code.
   - This keeps the retry prompt construction testable independently of I/O.

3. **`backend/tests/test_error_recovery.py`** — new test file covering retry behaviors.

4. **`backend/tests/test_chat.py`** — update `test_chat_endpoint_streams_error_on_execution_failure` (line 365). After Step 11, a single execution failure triggers a retry. The test must mock both the first and retry LLM calls. Alternatively, the existing test can mock both attempts to fail so it still expects an error event.

5. **`frontend/src/components/MessageBubble.tsx`** — update the error display:
   - When `message.error` is present, show a friendly wrapper message like "I couldn't execute the analysis. Try rephrasing your question or being more specific." followed by the technical error in a collapsible detail.
   - Optionally show a "retrying..." indicator if the `retrying` SSE event is adopted.

6. **`frontend/src/api.ts`** — if a `retrying` SSE event is added, add it to the switch statement and the `ChatCallbacks` interface.

7. **`frontend/src/store.ts`** — possibly add a `retrying?: boolean` field to `Message` if the frontend needs to show retry state.

### Function decomposition

- **Pure function (testable without mocks):** `build_retry_messages(original_question, failed_code, error_traceback, conversation_history)` in `llm.py`. Constructs the messages array for the retry LLM call. The retry message should say something like: "The following code failed with an error. Please fix the code and try again.\n\nOriginal code:\n```\n{code}\n```\n\nError:\n```\n{traceback}\n```"
- **I/O logic (in event_generator):** The retry orchestration stays in `main.py`'s `event_generator` since it needs access to session state, SSE yielding, and the execute_code call. This avoids the implementation plan's suggestion of a `generate_chat_response_with_retry()` in `llm.py` that would couple LLM calls with code execution — keeping them separate preserves the current clean I/O boundary.

### Key design decisions

1. **Retry count: 1** — the implementation plan specifies "Maximum retry count is 1 (original + 1 retry)." This is hardcoded as a constant `MAX_CODE_RETRIES = 1` in `main.py`.

2. **Retry scope: execution errors only** — only `exec_result["error"]` (code execution failures) trigger a retry. LLM API errors (network, auth, rate limit) and JSON parse errors are NOT retried — they are fundamentally different failure modes where re-prompting won't help.

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

## Open questions requiring user input

### Q1: Should the user see the retry happening?

**Option A — Silent retry:** The backend retries invisibly. The user either sees a successful result (if retry works) or an error (if both fail). Simpler to implement, no new SSE event type needed.

**Option B — Visible retry with SSE event:** The backend yields a `retrying` SSE event before the retry attempt. The frontend shows a brief "Retrying analysis..." indicator. This is more transparent but adds a new SSE event type, a new callback in `api.ts`, and a new field on `Message` in `store.ts`.

**Recommendation:** Option A (silent retry) for simplicity. The retry happens in ~2-5 seconds (one additional LLM call). If it succeeds, the user never needs to know. If it fails, the friendly error message is sufficient.

### Q2: What qualifies as a retryable error vs. a permanent failure?

**Proposed classification:**
- **Retryable (trigger retry):** `exec_result["error"]` is truthy — the LLM-generated code failed at runtime (NameError, TypeError, AttributeError, pandas errors, etc.). The LLM can plausibly fix these given the traceback.
- **NOT retryable (immediate error):** LLM API call exception (network, auth, rate limit), JSON parse failure from `parse_chat_response`, timeout from executor ("Code execution timed out"). These won't be fixed by re-prompting.

**Edge case — timeouts:** Should a timeout be retried? The LLM might generate more efficient code on retry, but it might also generate equally slow code, doubling the user's wait time. Proposed: do NOT retry timeouts.

### Q3: Should error + retry context be added to conversation_history?

**Proposed:** No. Only the final successful exchange (or the final failed exchange) is added to `conversation_history`. The retry context (failed code + traceback) is ephemeral — it's included in the messages for the retry LLM call but not persisted. This prevents the conversation history from being polluted with failed intermediate attempts, which would confuse the LLM on subsequent turns.

### Q4: Frontend error message — how friendly?

**Option A — Replace raw error entirely:** Show only "I couldn't execute the analysis. Try rephrasing your question." No technical detail visible.

**Option B — Friendly wrapper + collapsible technical detail:** Show the friendly message prominently, with a "Show details" toggle that reveals the raw traceback. This helps advanced users debug while keeping the default experience clean.

**Recommendation:** Option B — matches the existing "Show code" toggle pattern in `MessageBubble.tsx` (line 118-149).

### Q5: Should the existing `test_chat_endpoint_streams_error_on_execution_failure` be updated?

After Step 11, a single execution failure triggers a retry rather than an immediate SSE error. This existing test (test_chat.py line 365) mocks a single failed execution and expects an error event. It will need to either:
- **(A)** Be updated to mock both the first and retry LLM calls (both producing failing code), so it still expects the error event after exhausting retries.
- **(B)** Be left as-is if the mock setup happens to work (the single mock return value would be reused for both attempts).

**Recommendation:** Option A — explicitly update the test to mock two failed attempts. This documents the retry behavior and prevents the test from being fragile.

---

Does this plan look good? Would you like to adjust the scope, implementation approach, or phasing before I begin?
