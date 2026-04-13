# Reconnaissance: Runtime Observability

Branch-scoped artifact — remove upon merge to main.

Organization: by area of the codebase, not by abstract category. Each section covers one file or module — its role, dependencies, test coverage, what changes, and risk. Read each section independently. Inspired by clean code principles (guard clause pattern applied to documentation).

**Overall blast radius: Cross-cutting.** The change touches shared infrastructure (Session dataclass, error handling, multiple endpoints) and adds cross-cutting concerns (context buffer writes at every boundary, top-level exception handler wrapping all endpoints).

---

## Session State — `backend/session.py`

**What's here:** `Session` dataclass (14 fields) and `SessionStore` (create/get/delete). Central state carrier — every endpoint reads session fields.

**Who depends on it:**
- `main.py:84` — `SessionStore()` as module-level singleton
- `main.py:396` — `session_store.create()` in `/api/upload`
- `main.py:438,693,764,608,968` — `session_store.get()` in every endpoint
- Every endpoint reads: `dataframes`, `conversation_history`, `code_history`, `exec_namespace`, `api_key`, `provider`, `model`, `ml_*`

**Test coverage:** 14 tests in `test_session.py` — create, get, delete, isolation, namespace init. **Gaps:** `provider`/`model` storage untested (medium risk — `diagnose()` reads these). `conversation_history` mutation pattern untested (medium risk — passed in `DiagnosisRequest`).

**What changes:** Add `context_buffer: list` field with default empty list.

**Risk: Low.** Additive field, no existing callers read it. Default factory means `SessionStore.create()` needs no changes.

---

## Route Handlers — `backend/main.py`

**What's here:** ~1,077 lines. 9 route handlers, SSE streaming, retry logic, ML helpers, utilities. 16+ explicit non-200 responses. 2 SSE streaming endpoints (`/api/chat`, `/api/ml-step`).

**Who depends on it:**
- `frontend/src/api.ts` — every API function maps to one endpoint
- `test_chat.py` (5 tests), `test_clean.py` (thorough), `test_upload.py`, `test_error_recovery.py` (13 tests), `test_ml_workflow.py`, `test_validate_key.py`

**Test coverage:** Good for happy paths and expected errors. **Gaps:**
- Streaming generator crash mid-stream (HIGH — uncaught exception paths)
- `_build_ml_prompt()` exceptions (medium — `infer_problem_type()` can raise)
- `generate_summary()` error in `/api/upload` (medium — no try/except)
- `truncate_history()` ~line 460 (no try/except)

**What changes:** Instrumentation at 4 boundary call sites. Top-level exception handler. Generator-level wrappers for SSE. New `/api/bug-report` endpoint.

**Risk: HIGH.** The exception handler is the single highest-risk piece — must wrap all endpoints without interfering with 16+ error responses and 2 SSE patterns. This drives the preparatory refactor in the implementation plan.

---

## LLM Calls — `backend/llm.py`

**What's here:** ~994 lines. `call_llm_chat()`, `call_llm()`, `parse_chat_response()`, `generate_summary()`. Call functions raise exceptions; parse functions return error dicts.

**Who depends on it:** `main.py` (every LLM endpoint). Will be called by `troubleshooter.py:diagnose()`.

**Test coverage:** Partial in `test_llm.py` — code fence stripping, summary prompt, response parsing.

**What changes:** Nothing. Instrumentation happens at call sites. `diagnose()` calls `call_llm_chat()` but the interface is unchanged.

**Risk: Low.** No changes. But `troubleshooter.py` depends on `call_llm_chat()` working with session's `provider`/`model` — if silently None (see session.py gap), diagnosis fails.

---

## Code Execution — `backend/executor.py`

**What's here:** 261 lines. `execute_code()` — subprocess sandbox. Returns dict, never raises.

**Test coverage:** 12 tests in `test_executor.py` — good coverage.

**What changes:** Nothing. Instrumentation at call sites.

**Risk: None.**

---

## Data Cleaning — `backend/clean.py`

**What's here:** 102 lines. Pure functions. Raises exceptions for invalid inputs.

**Test coverage:** Thorough in `test_clean.py`.

**What changes:** Nothing. Instrumentation at `/api/clean` endpoint.

**Risk: None.**

---

## Frontend — `ChatPanel.tsx`, `api.ts`, `App.tsx`

**What's here:** `ChatPanel.tsx` — full-viewport flexbox chat. `api.ts` (445 lines) — API gateway with `apiFetch()` and SSE streaming. Z-index: 1100/1200/1300 for help system.

**Test coverage:** `ChatPanel.test.tsx` covers rendering and streaming.

**What changes:** `api.ts` gets `submitBugReport()`. `App.tsx` renders new `BugReportWidget` as sibling. `ChatPanel.tsx` NOT modified.

**Risk: Medium.** CSS/layout conflicts — FAB and help button both bottom-right. Z-index must stay below 1100. Widget must not interfere with `isStreaming` state.

---

## New Module — `backend/troubleshooter.py`

**What's here:** Does not exist yet.

**Will contain:** `ContextEntry`, `DiagnosisRequest`, `Diagnosis` dataclasses. `diagnose()`, `invoke_fix_agent()`, `create_fix_pr()`, `handle_systemic_error()`. Managed agent setup. Diagnosis prompt template.

**Will call:** `llm.py:call_llm_chat()`, `anthropic` SDK (managed agents), `PyGithub`.

**Will be called by:** `main.py` exception handler (imports `ContextEntry`, calls `diagnose()`, spawns `handle_systemic_error()`).

**Risk: Low.** New code, no existing callers. But every function needs graceful degradation — failures must never reach the user.

---

## Pre-Existing Bugs Found

Out of scope but the exception handler must not mask them.

1. **Missing `done` event in ML training error** (~line 1038): `error` SSE event emitted but no `done` follows. Client may hang.

2. **`generate_summary()` error leaks into response** (~line 411): Failed LLM call inserts `{"error": "..."}` as `summary` — user sees malformed response. This is handled (not unhandled), so the top-level handler must not interfere.

---

## Risk Summary

### Risk 1: Exception handler breaks existing error handling (HIGH)

**Problem:** 16+ explicit non-200 responses must not be intercepted.

**Why safe:** FastAPI's `@app.exception_handler(Exception)` only fires for unhandled exceptions, not `return JSONResponse(status_code=400)`. SSE needs separate treatment (Risk 2).

**Mitigation:** Characterization tests for all error responses before adding handler. Preparatory refactor makes it auditable.

### Risk 2: SSE streaming + exception handler (HIGH)

**Problem:** Once streaming starts, headers are sent — can't return JSON error. Handler may not fire.

**Uncaught paths:** `truncate_history()` (~460), `_build_ml_prompt()` (~1004, `infer_problem_type()` raises), `_update_ml_session_state()` (~1048), `conversation_history.append()`.

**Mitigation:** Try/except inside generators — yield SSE error event, write buffer entry, trigger troubleshooter.

### Risk 3: Buffer writes affect behavior (MEDIUM)

**Problem:** Instrumentation side effects must not crash endpoints or add latency.

**Mitigation:** Wrap in try/except with silent logging. Simple dict/list ops — failure unlikely.

### Risk 4: Frontend layout conflicts (MEDIUM)

**Problem:** FAB and help trigger both bottom-right. Z-index coordination needed.

**Mitigation:** FAB z-index below 1100. Position above input bar, not near help button.

### Risk 5: Managed agent cost (MEDIUM)

**Problem:** Each systemic error → full agent session (LLM calls, clone, pytest).

**Mitigation:** Graceful degradation if env vars missing. Console logging of duration/outcome.
