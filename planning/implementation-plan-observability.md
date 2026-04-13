# Implementation Plan: Runtime Observability

Branch-scoped artifact — remove upon merge to main.

---

## Overview

Implement the full observability strategy: context buffer, instrumentation at system boundaries, system-detected error path (diagnose → managed agent fix → PR), user-reported bug path, and frontend bug-report widget. Includes a preparatory refactor of `main.py` to isolate the change points.

---

## Step sequencing

### Step 1: Preparatory refactor — extract routes from `main.py`

**What:** Split `main.py` (~1,077 lines) into focused route modules using FastAPI `APIRouter`. Each endpoint group gets its own file under `backend/routes/`. `main.py` becomes app setup, CORS, router includes, and session store.

**Why first:** The reconnaissance identified the top-level exception handler as the highest-risk piece. It needs to wrap all endpoints without interfering with 16+ existing error responses and 2 SSE streaming patterns. That's much easier to audit and test when `main.py` is ~100 lines instead of ~1,077. The refactor also means instrumentation code (Steps 3-4) lands next to the boundary call sites in focused modules rather than buried in a monolith.

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

### Step 2: Context buffer foundation

**What:** Define `ContextEntry` dataclass and buffer helpers in `troubleshooter.py`. Add `context_buffer: list` field to `Session` dataclass with FIFO cap at 20 entries.

**Why second:** Everything else depends on this — instrumentation (Step 3), the exception handler (Step 4), and the troubleshooter pipeline (Steps 5-6) all read from or write to the buffer. Building and testing the data model first means Steps 3-6 have a stable foundation.

**Dependencies:** None (Step 1 is structural only — this doesn't depend on the refactor being complete, but it's sequenced after for clarity).

**Scope:** `ContextEntry` dataclass, buffer append helper (with FIFO truncation), `Session.context_buffer` field. No instrumentation yet — the buffer exists but nothing writes to it.

---

### Step 3: Instrumentation at system boundaries

**What:** Add context buffer entries at the 4 boundary call sites: LLM calls, code execution, file parsing, and data cleaning. Each entry captures actual inputs, outputs, and operation-specific metadata per the observability strategy.

**Why third:** The buffer exists (Step 2). Now we populate it. This must happen before the exception handler (Step 4) because the handler passes the buffer to the troubleshooter — an empty buffer has no diagnostic value.

**Dependencies:** Step 2 (buffer and `ContextEntry` exist).

**Scope:** Modifications to route modules (or `main.py` if Step 1 hasn't landed yet — the instrumentation logic is the same either way). Each call site gets a buffer append after the boundary operation completes. Buffer writes are wrapped defensively — a failure in instrumentation must never crash the endpoint.

**Sub-steps (can be done independently per boundary):**
1. LLM calls — in `/api/chat` and `/api/ml-step` (2 call sites each for `call_llm_chat`, 1 for `generate_summary`)
2. Code execution — in `/api/chat` and `/api/ml-step` (after `execute_code()`)
3. File parsing — in `/api/upload` (after `parse_dataframes_from_bytes()` + session creation)
4. Data cleaning — in `/api/clean` (before/after `apply_cleaning_action()`)

---

### Step 4: Top-level exception handler + diagnosis

**What:** Add a FastAPI exception handler that catches unhandled exceptions, builds a `DiagnosisRequest`, calls `diagnose()`, and returns a friendly error to the user. Define `DiagnosisRequest`, `Diagnosis` dataclasses and the `diagnose()` function (single LLM call for error classification) in `troubleshooter.py`.

**Why fourth:** The buffer is populated (Step 3), so the troubleshooter has real evidence to work with. This step delivers the first user-visible improvement: friendly error messages instead of stack traces.

**Dependencies:** Steps 2-3 (buffer exists and is populated). Step 1 makes this easier to implement but isn't strictly required.

**Key risk:** Must not intercept existing 400/404 responses or SSE streaming error flows. Reconnaissance identified this as the highest-risk area. SSE streaming endpoints need a separate approach — a try/except wrapper inside the generator that catches uncaught exceptions, yields an error event, and triggers the troubleshooter.

**Scope:**
- `DiagnosisRequest` and `Diagnosis` dataclasses in `troubleshooter.py`
- `diagnose()` function with classification prompt (transient / user_caused / systemic)
- FastAPI `@app.exception_handler(Exception)` for non-streaming endpoints
- Generator-level exception wrapper for SSE streaming endpoints
- Graceful degradation: if no API key is available, return a generic friendly message without LLM classification

---

### Step 5: Managed agent fix generation + PR creation

**What:** Implement `invoke_fix_agent()` and `create_fix_pr()` in `troubleshooter.py`. Set up the managed agent (one-time at app startup) with a system prompt that includes brownfield harness principles. When `diagnose()` classifies an error as systemic, spawn a background task that invokes the managed agent and opens a PR from the result.

**Why fifth:** Diagnosis (Step 4) is working — we can classify errors. Now we add the automated fix pipeline for systemic errors. This is the most complex step but also the most isolated — it runs in the background and never affects the user's request.

**Dependencies:** Step 4 (diagnosis and classification working). `PyGithub` dependency added to `requirements.txt`.

**Scope:**
- Managed agent creation at startup (`client.beta.agents.create()`) with harness-aware system prompt
- Cloud environment creation (`client.beta.environments.create()`) with pytest and networking
- `invoke_fix_agent()` — creates session, sends diagnosis, polls for completion
- `create_fix_pr()` — uses PyGithub to open PR from the agent's committed branch
- `handle_systemic_error()` — background task orchestrator (diagnose → agent → PR)
- Graceful degradation at each step: missing API key → skip agent; missing GitHub token → skip PR; agent failure → log and stop; PR failure → log and stop

---

### Step 6: User-reported bug path (backend)

**What:** Add `POST /api/bug-report` endpoint that accepts `{session_id, message}`, builds a `DiagnosisRequest` with `error_type="user_reported"`, and feeds it into the same troubleshooter pipeline. Returns a short acknowledgment with at most one clarifying question.

**Why sixth:** The full pipeline exists (Steps 2-5). Now we add the second input path. This is a thin endpoint — the heavy lifting is all in the existing pipeline.

**Dependencies:** Steps 4-5 (diagnosis and fix pipeline working).

**Scope:** New endpoint (in `routes/bug_report.py` if refactored, or in `main.py`). Reuses `DiagnosisRequest`, `diagnose()`, and `handle_systemic_error()` from `troubleshooter.py`. The only new logic is building the `DiagnosisRequest` from a user message instead of an exception.

---

### Step 7: Frontend bug-report widget

**What:** Build the `BugReportWidget` React component (circular FAB + compact chat window) and add `submitBugReport()` to `api.ts`. Wire it into the app as a sibling of ChatPanel.

**Why last:** The backend endpoint exists (Step 6). The frontend is the thinnest layer — it's a UI that calls one endpoint. Building it last means we can test the full backend pipeline via API before adding the UI.

**Dependencies:** Step 6 (backend endpoint working).

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
Step 2 (context buffer foundation)
  │
  ▼
Step 3 (instrumentation at boundaries)
  │
  ▼
Step 4 (exception handler + diagnosis)
  │
  ▼
Step 5 (managed agent + PR creation)
  │
  ▼
Step 6 (bug-report endpoint)
  │
  ▼
Step 7 (frontend widget)
```

Linear dependency chain. Each step builds on the previous. Steps 3a-3d (individual boundary instruments) can be parallelized within Step 3, but all other steps are sequential.

---

## Key sequencing decisions

**Why refactor first, not last?** The refactor makes every subsequent step cleaner — instrumentation lands in focused modules, the exception handler sits alone in a small `main.py`, and the new endpoint gets its own route file. Refactoring after would mean instrumenting `main.py` at 1,077 lines and then moving everything — higher risk of breaking the new code during the move.

**Why instrumentation before the exception handler?** The handler's value depends on the buffer having content. An exception handler without a populated buffer can classify errors but can't diagnose root causes or write reproduction steps. Instrument first, then wire up the handler.

**Why the managed agent before the bug-report path?** Both paths feed into the same pipeline. Building the full pipeline (diagnose → fix → PR) on the system-detected path first means the user-reported path just needs a thin endpoint that reuses everything.

**Why frontend last?** The frontend is a thin client that calls one endpoint. Every other step can be tested via API or unit tests. The frontend adds visual verification but no new logic.

---

## What each step delivers (incremental value)

| Step | User-visible value | Developer-visible value |
|------|-------------------|------------------------|
| 1. Refactor | None | Cleaner codebase, easier to maintain |
| 2. Buffer | None | Buffer exists, can inspect in debugger |
| 3. Instrumentation | None | Buffer populated — can inspect operation history in debugger |
| 4. Exception handler | Friendly error messages instead of stack traces | Error classification logged, diagnosis available |
| 5. Managed agent + PR | None (runs in background) | Systemic bugs produce PRs with diagnosis + fix |
| 6. Bug-report endpoint | None yet (no UI) | Endpoint testable via curl/API |
| 7. Frontend widget | Users can report bugs via chat widget | Full pipeline end-to-end |
