# Implementation Plan: Runtime Observability

Branch-scoped artifact — remove upon merge to main.

---

## Overview

Implement the full observability strategy: context buffer, instrumentation at system boundaries, system-detected error path (diagnose → managed agent fix → PR), user-reported bug path, and frontend bug-report widget. Includes a preparatory refactor of `main.py` to isolate the change points and fixes for pre-existing bugs found during reconnaissance.

---

## Step sequencing

### Step 1: Preparatory refactor — extract routes from `main.py`

**What:** Split `main.py` (~1,077 lines) into focused route modules using FastAPI `APIRouter`. Each endpoint group gets its own file under `backend/routes/`. `main.py` becomes app setup, CORS, router includes, and session store.

**Why first:** The reconnaissance identified the top-level exception handler as the highest-risk piece. It needs to wrap all endpoints without interfering with 16+ existing error responses and 2 SSE streaming patterns. That's much easier to audit and test when `main.py` is ~100 lines instead of ~1,077. The refactor also means instrumentation code (Steps 4-5) lands next to the boundary call sites in focused modules rather than buried in a monolith.

**Dependencies:** None — this is purely structural.

**Brownfield phase:** B2 (preparatory refactor). Gets its own characterization tests covering every existing endpoint's request shape, response shape, status codes, and error paths. All existing tests must continue passing. Zero behavior change.

**Route module split:**
- `routes/upload.py` — `/api/upload` + parse/metadata helpers
- `routes/chat.py` — `/api/chat` + retry/streaming/SSE helpers
- `routes/clean.py` — `/api/clean`, `/api/clean/reset`
- `routes/ml.py` — `/api/ml-step` + ML prompt/state helpers
- `routes/export.py` — `/api/export/{session_id}`
- `routes/keys.py` — `/api/validate-key`, `/api/models`, `/api/health`

---

### Step 2: Fix pre-existing bugs found during reconnaissance

**What:** Fix two bugs discovered during codebase reconnaissance. Both are in route handler code (post-refactor: in individual route modules).

**Bug 2a — Missing `done` event in ML training error path** (`main.py` ~line 1038, post-refactor: `routes/ml.py`): When code execution fails during the ML training stage, an `error` SSE event is emitted but no `done` event follows. The client may hang waiting for stream completion. **Fix:** Add a `done` event yield after the `error` event in the training-stage error path, matching the pattern used in all other SSE error paths.

**Bug 2b — `generate_summary()` error leaks into response** (`main.py` ~line 411, post-refactor: `routes/upload.py`): If the LLM call for dataset summary fails, `{"error": "..."}` is inserted as `response_content["summary"]` — the user sees a malformed response instead of a clean fallback. **Fix:** Catch the error and substitute a graceful fallback summary (e.g., "Summary unavailable") so the upload response shape is always clean.

**Why second:** These bugs live in code we're about to instrument (Steps 4-5) and wrap with an exception handler (Step 5). Fixing them now means: (1) the exception handler doesn't need to work around known-broken behavior, (2) the instrumentation captures clean operation flows, and (3) the characterization tests from Step 1 already cover these paths — we can write targeted regression tests against a clean baseline.

**Dependencies:** Step 1 (refactor complete, characterization tests in place). Fixing these in the focused route modules is cleaner than in the monolith.

**Scope:** Two targeted fixes, each with a regression test. No other behavior changes.

---

### Step 3: Context buffer foundation

**What:** Define `ContextEntry` dataclass and buffer helpers in `troubleshooter.py`. Add `context_buffer: list` field to `Session` dataclass with FIFO cap at 20 entries.

**Why third:** Everything else depends on this — instrumentation (Step 4), the exception handler (Step 5), and the troubleshooter pipeline (Steps 6-7) all read from or write to the buffer. Building and testing the data model first means Steps 4-7 have a stable foundation.

**Dependencies:** None (Step 1 is structural only — this doesn't depend on the refactor being complete, but it's sequenced after for clarity).

**Scope:** `ContextEntry` dataclass, buffer append helper (with FIFO truncation), `Session.context_buffer` field. No instrumentation yet — the buffer exists but nothing writes to it.

---

### Step 4: Instrumentation at system boundaries

**What:** Add context buffer entries at the 4 boundary call sites: LLM calls, code execution, file parsing, and data cleaning. Each entry captures actual inputs, outputs, and operation-specific metadata per the observability strategy.

**Why fourth:** The buffer exists (Step 3). Now we populate it. This must happen before the exception handler (Step 5) because the handler passes the buffer to the troubleshooter — an empty buffer has no diagnostic value.

**Dependencies:** Step 3 (buffer and `ContextEntry` exist).

**Scope:** Modifications to route modules. Each call site gets a buffer append after the boundary operation completes. Buffer writes are wrapped defensively — a failure in instrumentation must never crash the endpoint.

**Sub-steps (can be done independently per boundary):**
1. LLM calls — in `/api/chat` and `/api/ml-step` (2 call sites each for `call_llm_chat`, 1 for `generate_summary`)
2. Code execution — in `/api/chat` and `/api/ml-step` (after `execute_code()`)
3. File parsing — in `/api/upload` (after `parse_dataframes_from_bytes()` + session creation)
4. Data cleaning — in `/api/clean` (before/after `apply_cleaning_action()`)

---

### Step 5: Top-level exception handler + diagnosis

**What:** Add a FastAPI exception handler that catches unhandled exceptions, builds a `DiagnosisRequest`, calls `diagnose()`, and returns a friendly error to the user. Define `DiagnosisRequest`, `Diagnosis` dataclasses and the `diagnose()` function (single LLM call for error classification) in `troubleshooter.py`.

**Why fifth:** The buffer is populated (Step 4), so the troubleshooter has real evidence to work with. The pre-existing bugs are already fixed (Step 2), so the handler doesn't need to work around known-broken error paths. This step delivers the first user-visible improvement: friendly error messages instead of stack traces.

**Dependencies:** Steps 3-4 (buffer exists and is populated). Step 1 makes this easier to implement but isn't strictly required. Step 2 ensures the handler wraps clean code.

**Key risk:** Must not intercept existing 400/404 responses or SSE streaming error flows. Reconnaissance identified this as the highest-risk area. SSE streaming endpoints need a separate approach — a try/except wrapper inside the generator that catches uncaught exceptions, yields an error event, and triggers the troubleshooter.

**Scope:**
- `DiagnosisRequest` and `Diagnosis` dataclasses in `troubleshooter.py`
- `diagnose()` function with classification prompt (transient / user_caused / systemic)
- FastAPI `@app.exception_handler(Exception)` for non-streaming endpoints
- Generator-level exception wrapper for SSE streaming endpoints
- Graceful degradation: if no API key is available, return a generic friendly message without LLM classification

---

### Step 6: Managed agent fix generation + PR creation

**What:** Implement `invoke_fix_agent()` and `create_fix_pr()` in `troubleshooter.py`. Set up the managed agent (one-time at app startup) with a system prompt that includes brownfield harness principles. When `diagnose()` classifies an error as systemic, spawn a background task that invokes the managed agent and opens a PR from the result.

**Why sixth:** Diagnosis (Step 5) is working — we can classify errors. Now we add the automated fix pipeline for systemic errors. This is the most complex step but also the most isolated — it runs in the background and never affects the user's request.

**Dependencies:** Step 5 (diagnosis and classification working). `PyGithub` dependency added to `requirements.txt`.

**Scope:**
- Managed agent creation at startup (`client.beta.agents.create()`) with harness-aware system prompt
- Cloud environment creation (`client.beta.environments.create()`) with pytest and networking
- `invoke_fix_agent()` — creates session, sends diagnosis, polls for completion
- `create_fix_pr()` — uses PyGithub to open PR from the agent's committed branch
- `handle_systemic_error()` — background task orchestrator (diagnose → agent → PR)
- Graceful degradation at each step: missing API key → skip agent; missing GitHub token → skip PR; agent failure → log and stop; PR failure → log and stop

---

### Step 7: User-reported bug path (backend)

**What:** Add `POST /api/bug-report` endpoint that accepts `{session_id, message}`, builds a `DiagnosisRequest` with `error_type="user_reported"`, and feeds it into the same troubleshooter pipeline. Returns a short acknowledgment with at most one clarifying question.

**Why seventh:** The full pipeline exists (Steps 3-6). Now we add the second input path. This is a thin endpoint — the heavy lifting is all in the existing pipeline.

**Dependencies:** Steps 5-6 (diagnosis and fix pipeline working).

**Scope:** New endpoint (in `routes/bug_report.py`). Reuses `DiagnosisRequest`, `diagnose()`, and `handle_systemic_error()` from `troubleshooter.py`. The only new logic is building the `DiagnosisRequest` from a user message instead of an exception.

---

### Step 8: Frontend bug-report widget

**What:** Build the `BugReportWidget` React component (circular FAB + compact chat window) and add `submitBugReport()` to `api.ts`. Wire it into the app as a sibling of ChatPanel.

**Why last:** The backend endpoint exists (Step 7). The frontend is the thinnest layer — it's a UI that calls one endpoint. Building it last means we can test the full backend pipeline via API before adding the UI.

**Dependencies:** Step 7 (backend endpoint working).

**Scope:**
- `BugReportWidget.tsx` — FAB button (~40px circle, bottom-right), compact chat window (~340x380px), own message state, header with close button, input bar
- `api.ts` — `submitBugReport(sessionId, message)` function using `apiFetch()`
- `App.tsx` — render `BugReportWidget` as sibling alongside `ChatPanel` when on the chat screen
- Z-index below 1100 (under the existing help system)
- No modifications to ChatPanel, store, or existing components

---

## Dependency graph

```
Step 1 (refactor main.py)
  │
  ▼
Step 2 (fix pre-existing bugs)
  │
  ▼
Step 3 (context buffer foundation)
  │
  ▼
Step 4 (instrumentation at boundaries)
  │
  ▼
Step 5 (exception handler + diagnosis)
  │
  ▼
Step 6 (managed agent + PR creation)
  │
  ▼
Step 7 (bug-report endpoint)
  │
  ▼
Step 8 (frontend widget)
```

Linear dependency chain. Each step builds on the previous. Steps 4a-4d (individual boundary instruments) can be parallelized within Step 4, but all other steps are sequential.

---

## Key sequencing decisions

**Why refactor first, not last?** The refactor makes every subsequent step cleaner — instrumentation lands in focused modules, the exception handler sits alone in a small `main.py`, and the new endpoint gets its own route file. Refactoring after would mean instrumenting `main.py` at 1,077 lines and then moving everything — higher risk of breaking the new code during the move.

**Why fix pre-existing bugs before instrumentation?** The bugs are in code we're about to instrument and wrap with an exception handler. Fixing them first means the handler wraps clean behavior, instrumentation captures correct operation flows, and regression tests lock down the fixes before new code lands on top.

**Why instrumentation before the exception handler?** The handler's value depends on the buffer having content. An exception handler without a populated buffer can classify errors but can't diagnose root causes or write reproduction steps. Instrument first, then wire up the handler.

**Why the managed agent before the bug-report path?** Both paths feed into the same pipeline. Building the full pipeline (diagnose → fix → PR) on the system-detected path first means the user-reported path just needs a thin endpoint that reuses everything.

**Why frontend last?** The frontend is a thin client that calls one endpoint. Every other step can be tested via API or unit tests. The frontend adds visual verification but no new logic.

---

## What each step delivers (incremental value)

| Step | User-visible value | Developer-visible value |
|------|-------------------|------------------------|
| 1. Refactor | None | Cleaner codebase, easier to maintain |
| 2. Fix bugs | ML training errors no longer hang client; upload summary errors are clean | 2 regressions eliminated, regression tests added |
| 3. Buffer | None | Buffer exists, can inspect in debugger |
| 4. Instrumentation | None | Buffer populated — can inspect operation history in debugger |
| 5. Exception handler | Friendly error messages instead of stack traces | Error classification logged, diagnosis available |
| 6. Managed agent + PR | None (runs in background) | Systemic bugs produce PRs with diagnosis + fix |
| 7. Bug-report endpoint | None yet (no UI) | Endpoint testable via curl/API |
| 8. Frontend widget | Users can report bugs via chat widget | Full pipeline end-to-end |
