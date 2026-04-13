# Reconnaissance: Runtime Observability

Branch-scoped artifact — remove upon merge to main.

---

## 1. Affected files and functions

### Backend — Modified

| File | Functions/Areas affected | What changes |
|------|------------------------|-------------|
| `backend/session.py` | `Session` dataclass | Add `context_buffer: list` field |
| `backend/main.py` | `/api/upload`, `/api/chat`, `/api/clean`, `/api/ml-step`, app-level error handling | Add instrumentation at boundary call sites; add top-level exception handler; add `POST /api/bug-report` endpoint |
| `backend/requirements.txt` | — | Add `PyGithub` dependency |

### Backend — New

| File | Purpose |
|------|---------|
| `backend/troubleshooter.py` | `ContextEntry` dataclass, `DiagnosisRequest`/`Diagnosis` dataclasses, `diagnose()`, `invoke_fix_agent()`, `create_fix_pr()`, `handle_systemic_error()`, managed agent setup |

### Frontend — Modified

| File | What changes |
|------|-------------|
| `frontend/src/api.ts` | Add `submitBugReport()` function |

### Frontend — New

| File | Purpose |
|------|---------|
| `frontend/src/components/BugReportWidget.tsx` | FAB button + compact chat widget |

### Not modified

| File | Why |
|------|-----|
| `backend/llm.py` | Instrumentation happens at call sites in `main.py`, not inside `llm.py`. `call_llm_chat()` is called by `troubleshooter.py` but its interface is unchanged. |
| `backend/executor.py` | Instrumentation happens at call sites in `main.py`. `execute_code()` interface unchanged. |
| `backend/clean.py` | Pure functions. Instrumentation happens in `/api/clean` endpoint. |
| `backend/exporter.py` | Not a system boundary. No instrumentation needed. |
| `frontend/src/components/ChatPanel.tsx` | Bug widget is a sibling component, not a modification to ChatPanel. |

---

## 2. Dependency map

### Upstream (who calls what we're changing)

**`Session` dataclass (session.py):**
- `main.py:84` — `SessionStore()` instantiated as module-level singleton
- `main.py:396` — `session_store.create()` in `/api/upload`
- `main.py:438,693,764,608,968` — `session_store.get()` in every endpoint that needs session state
- Every endpoint reads session fields: `dataframes`, `conversation_history`, `code_history`, `exec_namespace`, `api_key`, `provider`, `model`, `ml_*`
- `tests/test_session.py` — 14 tests covering CRUD, field initialization, DataFrame isolation

**`main.py` endpoints:**
- `frontend/src/api.ts` — every API function maps to one endpoint
- `tests/test_chat.py` — 5 tests for `/api/chat`
- `tests/test_clean.py` — full coverage for `/api/clean` and `/api/clean/reset`
- `tests/test_upload.py` — coverage for `/api/upload`
- `tests/test_error_recovery.py` — 13 tests for retry logic
- `tests/test_ml_workflow.py` — coverage for `/api/ml-step`
- `tests/test_validate_key.py` — coverage for `/api/validate-key`

### Downstream (what our changes will call)

**`troubleshooter.py` (new) will call:**
- `llm.py:call_llm_chat()` — for `diagnose()` (single LLM call for classification)
- `anthropic` SDK — `client.beta.agents.create()`, `client.beta.sessions.create()`, `client.beta.sessions.events.send()` for managed agent
- `PyGithub` — for `create_fix_pr()`

**`main.py` instrumentation will call:**
- `troubleshooter.py:ContextEntry` — dataclass import
- `troubleshooter.py:diagnose()` — from top-level exception handler
- `troubleshooter.py:handle_systemic_error()` — spawned as background task

---

## 3. Test coverage status

### What IS covered

| Area | Test file | Coverage quality |
|------|-----------|-----------------|
| Session CRUD | `test_session.py` (14 tests) | Good — create, get, delete, isolation, namespace init |
| Chat happy path | `test_chat.py` (5 tests) | Good — 404, 400, streaming, history update, code history |
| Chat retry/error recovery | `test_error_recovery.py` (13 tests) | Thorough — exec fail, LLM fail, parse fail, timeout, curly braces |
| Upload parsing | `test_upload.py` | Good — CSV, Excel, multi-sheet, error handling |
| Cleaning pure functions | `test_clean.py` | Thorough — all actions, edge cases, endpoint validation, multi-DataFrame |
| ML workflow | `test_ml_workflow.py` | Good — stage progression, state management |
| Executor | `test_executor.py` (12 tests) | Good — stdout, figures, change detection, security, timeout |
| LLM parsing | `test_llm.py` | Partial — code fence stripping, summary prompt, response parsing |

### What is NOT covered (gaps in blast radius)

| Gap | Risk | Relevance to our change |
|-----|------|------------------------|
| `Session.provider` and `Session.model` storage/retrieval | Medium — used in every LLM call | We read these in `diagnose()` to call `call_llm_chat()`. If they're silently None, diagnosis call fails. |
| `Session.original_filename` storage | Low | Not relevant — we don't use this field. |
| `conversation_history` mutation pattern | Medium — format assumed by `build_chat_messages()` | We pass `conversation_history` in `DiagnosisRequest`. If format is wrong, diagnosis gets bad input. |
| `code_history` mutation pattern | Low | Not relevant — we don't read code_history. |
| ML field initialization (all start as `None`) | Low | We pass `ml_state` in `DiagnosisRequest` but only for informational context. |
| `_build_ml_prompt()` exception paths | Medium — unguarded `infer_problem_type()` can raise | The top-level exception handler would catch these. We need to verify it doesn't interfere with the existing SSE error flow. |
| `generate_summary()` error handling in `/api/upload` | Medium — no try/except wrapping | The top-level handler must not swallow the existing behavior (error dict inserted into response). |
| Streaming generator crash mid-stream | High — SSE endpoints have uncaught exception paths | The top-level exception handler must work correctly for SSE streaming endpoints, not just JSON endpoints. |
| Frontend: ChatPanel during streaming | Covered by `ChatPanel.test.tsx` | Need to verify BugReportWidget doesn't interfere with `isStreaming` state. |

### Existing bugs found during reconnaissance

1. **Missing `done` event in ML training error path** (`main.py` ~line 1038-1039): When code execution fails during ML training stage, an `error` SSE event is emitted but no `done` event follows. Out of scope for this change but worth noting.
2. **`generate_summary()` error leaks into response** (`main.py` ~line 411): If the LLM call fails, `{"error": "..."}` is inserted as `response_content["summary"]` — user sees malformed response. Out of scope but the top-level handler must not mask this existing behavior.

---

## 4. Blast radius classification

**Overall: Cross-cutting.**

The change touches shared infrastructure (Session dataclass, error handling, multiple endpoints) and adds new cross-cutting concerns (context buffer writes at every boundary, top-level exception handler that wraps all endpoints).

### Per-area breakdown

| Area | Blast radius | Test coverage | Caller count | Backward compatible? | Risk severity |
|------|-------------|---------------|-------------|---------------------|---------------|
| `Session.context_buffer` field | Interface | Yes (14 tests) | Every endpoint via `session_store.get()` | Yes — additive field, default empty list | Low — new field, no callers read it yet |
| Instrumentation in `/api/chat` | Contained | Yes (5 + 13 tests) | Frontend `sendChatMessage()` | Yes — side-effect only (buffer writes) | Low — buffer append is fire-and-forget |
| Instrumentation in `/api/upload` | Contained | Yes | Frontend `uploadFile()` | Yes — side-effect only | Low |
| Instrumentation in `/api/clean` | Contained | Yes (thorough) | Frontend `applyCleaningAction()` | Yes — side-effect only | Low |
| Instrumentation in `/api/ml-step` | Contained | Yes | Frontend `sendMlStep()` | Yes — side-effect only | Low |
| Top-level exception handler | **Cross-cutting** | **Partial** | All endpoints | **Must not break existing error paths** | **High — wrong implementation swallows 400/404s or breaks SSE streams** |
| `POST /api/bug-report` | Contained | None (new) | New frontend widget only | N/A — new endpoint | Low |
| `troubleshooter.py` | Contained | None (new) | `main.py` exception handler only | N/A — new module | Low |
| `BugReportWidget.tsx` | Contained | None (new) | `App.tsx` renders it as sibling | Must not interfere with ChatPanel layout or z-index | Medium — CSS/layout conflicts possible |
| `api.ts` addition | Contained | Existing pattern | New widget only | Yes — additive function | Low |

---

## 5. Key risks

### Risk 1: Top-level exception handler breaks existing error handling (HIGH)

The biggest risk. `main.py` has a complex error handling landscape:
- 16+ explicit non-200 responses (400, 404, 413, 502) that are *intentionally* returned by route handlers
- Two SSE streaming endpoints (`/api/chat`, `/api/ml-step`) where errors are streamed as events, not returned as JSON
- Broad `except Exception` blocks in `/api/upload` (line 381) and `/api/ml-step` (line 1014) that catch system boundary failures

The top-level handler must **only** catch exceptions that currently produce unhandled 500s. It must not intercept:
- Explicit `return JSONResponse(status_code=400, ...)` responses
- Explicit `return JSONResponse(status_code=404, ...)` responses
- Errors caught by endpoint-level try/except blocks
- SSE streaming errors (these are already yielded as events, not raised as exceptions)

**Mitigation:** FastAPI's `@app.exception_handler(Exception)` only fires for *unhandled* exceptions — it doesn't intercept `return JSONResponse(...)`. But SSE streaming generators need special attention: if an exception escapes the generator, FastAPI may not route it through the exception handler the same way.

### Risk 2: SSE streaming + exception handler interaction (HIGH)

The `/api/chat` and `/api/ml-step` endpoints return `StreamingResponse` with generator functions. If an unhandled exception occurs *inside* the generator (after streaming has started), the HTTP response headers have already been sent — you can't change the status code to 500. The exception handler may not fire at all, or it may fire but be unable to return a friendly JSON response because the response is already in-flight.

Reconnaissance found several uncaught exception paths inside streaming generators:
- `truncate_history()` at line ~460 (no try/except)
- `_build_ml_prompt()` at line ~1004 (calls `infer_problem_type()` which can raise ValueError)
- `_update_ml_session_state()` at line ~1048 (same)
- `conversation_history.append()` operations

**Mitigation:** The top-level handler works for non-streaming endpoints. For streaming endpoints, we likely need a try/except inside the generator itself that catches remaining uncaught exceptions, yields an SSE error event, writes a context buffer entry, and triggers the troubleshooter.

### Risk 3: Context buffer writes must not affect endpoint latency or behavior (MEDIUM)

Buffer writes are side effects — they must not slow down the user's request or change what the user sees. If a buffer write fails (e.g., due to a bug in `ContextEntry` construction), it must not crash the endpoint.

**Mitigation:** Wrap buffer writes in try/except that silently logs failures. Buffer writes are simple dict/list operations — failure is unlikely but must be handled defensively.

### Risk 4: Frontend BugReportWidget z-index and layout conflicts (MEDIUM)

The existing app has a z-index hierarchy: 1100 (help trigger button), 1200 (help overlay), 1300 (help panel). The bug-report FAB and widget must coordinate:
- FAB must not occlude the help trigger button (both bottom-right area)
- Widget must not conflict with the help panel overlay
- Widget must not cause layout shift in ChatPanel

**Mitigation:** Use z-index below 1100 for FAB and widget (they should go *under* the help system, not over it). Position FAB above the input bar, not in the top-right where the help button lives.

### Risk 5: Managed agent environment access and cost (MEDIUM)

The managed agent runs in Anthropic's cloud and needs to clone the repo, explore, fix, test, and commit. This involves:
- Network access to the Git remote (requires `TROUBLESHOOTER_GITHUB_TOKEN`)
- Multiple LLM calls (agent loop)
- Compute time for `pytest` execution in the cloud environment
- Cost per invocation (each systemic error triggers a full agent session)

**Mitigation:** The pipeline degrades gracefully if env vars are missing. But when it *does* run, cost and latency are real concerns. This should be monitored (console logging of agent session duration and outcome).
