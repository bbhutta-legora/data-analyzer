# Change Spec: Runtime Observability

Branch-scoped artifact — remove upon merge to main.

Organization: by area, not by abstract category. Each section is self-contained — read it, understand it, move on. Inspired by clean code principles (guard clause pattern applied to documentation: handle each concern fully so the reader can proceed without carrying it forward).

---

## Overview

The application has no structured runtime diagnostics. When an LLM call produces wrong output, generated code crashes, or a user sees a bad chart, the only trace is scattered `logger.info()` calls. Developers can't reconstruct what happened. Users can't report issues.

This change implements the observability strategy from `harness/OBSERVABILITY-STRATEGY.md`: a per-session context buffer, instrumentation at system boundaries, a two-path bug-catching pipeline (system-detected + user-reported), a troubleshooter agent that diagnoses and fixes systemic bugs, and automated PR creation.

---

## Area 1: Context Buffer

**What exists today:** `Session` dataclass in `backend/session.py` holds all mutable state (DataFrames, conversation history, code history, exec namespace, ML state). No operation history is tracked. `SessionStore` provides create/get/delete with no hook points for buffer management.

**What changes:**
- `Session` gains a `context_buffer: list` field, initialized empty, capped at 20 entries (FIFO).
- `ContextEntry` dataclass defined in `backend/troubleshooter.py` with fields: `timestamp`, `operation`, `input_actual`, `output_actual`, `success`, `error`, `metadata`.
- Buffer append helper enforces the FIFO cap — oldest entry dropped when buffer exceeds 20.
- Buffer is in-memory only. Not persisted. Discarded when session ends.

**Acceptance criteria:**
- When a session is created, `session.context_buffer` is an empty list.
- When the buffer exceeds 20 entries, the oldest entry is dropped.

**What must NOT break:**
- `SessionStore.create()` always succeeds and returns a valid session_id.
- `SessionStore.get()` returns `None` for unknown IDs (never raises).
- `SessionStore.delete()` returns `False` for unknown IDs (never raises).
- DataFrame isolation: working copies and originals are independent.
- `exec_namespace` populated with sandbox libraries + `dfs` dict + `print`.

---

## Area 2: Instrumentation at System Boundaries

Four boundaries instrumented because they're where non-determinism enters the system. Instrumentation happens at call sites in route handlers, NOT inside lower-level modules (`llm.py`, `executor.py`, `clean.py` stay unchanged). All buffer writes are fire-and-forget side effects wrapped defensively — a failure must never crash the endpoint.

### 2a: LLM Calls

**What exists today:** `call_llm_chat()` in `llm.py` calls Anthropic/OpenAI APIs. Called from `/api/chat` and `/api/ml-step`. Only `logger.info`/`logger.warning`. No structured capture.

**What changes:** After each `call_llm_chat()`, a `ContextEntry` with `operation="llm_call"` is appended. Metadata: model, purpose, parse success, parsed code, token usage.

**Acceptance criteria:** When an LLM call completes (success or failure), a `ContextEntry` is appended with the user's question as `input_actual`, raw LLM response as `output_actual`, and all metadata fields.

**What must NOT break:** `call_llm_chat()`/`call_llm()` provider dispatch. `parse_chat_response()` return shapes. Retry logic in `_attempt_chat_with_retries`. `generate_summary()` independence.

### 2b: Code Execution

**What exists today:** `execute_code()` in `executor.py` runs code in subprocess sandbox. Returns `{stdout, figures, error, dataframe_changed, new_dfs_pickle}`. No logging.

**What changes:** After each `execute_code()`, a `ContextEntry` with `operation="code_execution"` is appended. Metadata: namespace keys, figure count, execution time, DataFrame change status.

**Acceptance criteria:** When code is executed, a `ContextEntry` is appended with full code as `input_actual`, stdout/error as `output_actual`, and all metadata.

**What must NOT break:** Subprocess execution with timeout. Blocked builtins. Figure/stdout capture. DataFrame change detection.

### 2c: File Parsing

**What exists today:** `parse_dataframes_from_bytes()` in `main.py` parses CSV/Excel into DataFrames. Failures return 400. No capture of results.

**What changes:** After successful parsing in `/api/upload`, a `ContextEntry` with `operation="file_parse"` is appended. Metadata: resulting shape, columns with dtypes, missing value counts.

**Acceptance criteria:** When a file is parsed, a `ContextEntry` is appended with filename as `input_actual` and parse results as `output_actual`.

**What must NOT break:** `/api/upload` request/response shapes. Status codes (200, 400, 422).

### 2d: Data Cleaning

**What exists today:** `apply_cleaning_action()` in `clean.py` dispatches to pure functions. `logger.info()` at endpoint level. No before/after capture.

**What changes:** Around each `apply_cleaning_action()` in `/api/clean`, a `ContextEntry` with `operation="data_clean"` is appended. Metadata: action, target columns, before/after row counts, column lists, dtypes.

**Acceptance criteria:** When a cleaning action is applied, a `ContextEntry` is appended with action as `input_actual` and before/after summary as `output_actual`.

**What must NOT break:** Pure functions produce same transformations. `VALID_ACTIONS` unchanged. `/api/clean` and `/api/clean/reset` request/response shapes and status codes.

---

## Area 3: Exception Handler + Diagnosis

**What exists today:** Endpoints catch expected errors (missing session → 404, invalid input → 400). No top-level exception handler — unhandled exceptions produce FastAPI's default 500 with stack trace. LLM errors in `/api/chat` caught and streamed as SSE error events. Two SSE streaming endpoints (`/api/chat`, `/api/ml-step`) use `StreamingResponse` with generators.

**What changes:**
- FastAPI `@app.exception_handler(Exception)` catches unhandled exceptions from non-streaming endpoints. Builds `DiagnosisRequest`, calls `diagnose()`, returns friendly JSON error.
- For SSE streaming endpoints: try/except inside generators catches uncaught exceptions, yields SSE error event, writes buffer entry, triggers troubleshooter.
- `DiagnosisRequest` and `Diagnosis` dataclasses in `backend/troubleshooter.py`.
- `diagnose()` in `troubleshooter.py` (not `llm.py` — serves observability pipeline, not user's analysis). Calls `call_llm_chat()` for API transport.
- Classifies: transient / user_caused / systemic. For systemic: returns friendly message immediately, spawns background task.
- No API key available → generic friendly message without LLM classification.

**Acceptance criteria:**
- Unhandled exceptions return friendly JSON error, not stack trace.
- Transient/user_caused → no background task.
- No API key → generic friendly message still returned.

**What must NOT break:**
- Explicit 400s for invalid input continue to return 400.
- Explicit 404s for missing sessions continue to return 404.
- SSE error events in `/api/chat` and `/api/ml-step` continue streaming.
- Handler only catches currently-unhandled 500s — no interception of handled error paths.
- All 9 endpoint request/response contracts unchanged.

---

## Area 4: Managed Agent + PR Creation

**What exists today:** No GitHub integration. No agent infrastructure.

**What changes:**
- At startup: managed agent via `client.beta.agents.create()` with brownfield harness system prompt. Cloud environment via `client.beta.environments.create()` with pytest and networking.
- `invoke_fix_agent()` creates session, sends diagnosis, polls for completion. Agent clones repo, explores, fixes, tests, commits, pushes.
- `create_fix_pr()` uses PyGithub to open PR from agent's branch.
- `handle_systemic_error()` orchestrates: diagnose → agent → PR.
- Graceful degradation at each step: missing key → skip; failure → log and stop.

**Acceptance criteria:**
- Systemic classification → background task → agent session → PR.
- PR body: diagnosis, reproduction steps, fix description, files changed. Never auto-merged.
- Agent code follows harness conventions (enforced via system prompt).
- Missing `ANTHROPIC_API_KEY` → pipeline unavailable.
- Missing `TROUBLESHOOTER_GITHUB_TOKEN` or `TROUBLESHOOTER_REPO_URL` → Phases 2-3 skipped.
- Failures logged, never propagated to user.

**What must NOT break:** Nothing (new infrastructure). But background task must never affect the user's request.

---

## Area 5: Bug-Report Endpoint

**What exists today:** No bug-report mechanism.

**What changes:**
- `POST /api/bug-report` accepts `{session_id, message}`.
- Builds `DiagnosisRequest` with `error_type="user_reported"`, feeds into same pipeline.
- Returns short acknowledgment + at most one clarifying question.

**Acceptance criteria:**
- Bug report builds `DiagnosisRequest` with `error_type="user_reported"` and processes through pipeline.
- Response is short acknowledgment with at most one clarifying question.

**What must NOT break:** Nothing (new endpoint). Must not interfere with existing routing.

---

## Area 6: Frontend Widget

**What exists today:** Single-screen chat (`ChatPanel`) with header, scrollable messages, input bar. Z-index: 1100 (help trigger), 1200 (help overlay), 1300 (help panel). No bug-report UI.

**What changes:**
- `BugReportWidget.tsx` — circular FAB (~40px), bottom-right, above input bar. Opens compact chat (~340x380px).
- Widget has own header, scrollable messages, text input. Sends to `POST /api/bug-report`.
- `api.ts` gains `submitBugReport()` using existing `apiFetch()`.
- `App.tsx` renders widget as sibling of `ChatPanel`. Z-index below 1100.

**Acceptance criteria:**
- FAB click opens compact widget in bottom-right.
- Main chat stays fully interactive with no layout shift.

**What must NOT break:**
- ChatPanel renders and behaves identically.
- Header buttons (Reset, Build a Model, Export) functional.
- No layout shift when widget is closed.
- No modifications to ChatPanel, store, or existing components.

---

## Area 7: Dependencies & Environment

**New module:** `backend/troubleshooter.py` — all dataclasses, diagnosis, agent invocation, PR creation, prompt template.

**New dependency:** `PyGithub` in `requirements.txt`. Managed agent uses existing `anthropic` SDK.

**New environment variables:**

| Variable | Purpose | If missing |
|----------|---------|------------|
| `TROUBLESHOOTER_GITHUB_TOKEN` | Repo access for git push + PR | PR skipped; diagnosis logged |
| `TROUBLESHOOTER_REPO_URL` | Repo URL for agent to clone | Phases 2-3 skipped |

No separate API key — managed agent uses same `ANTHROPIC_API_KEY`.

---

## Out of Scope

- Persistent log storage — buffer is in-memory, session-scoped
- Log aggregation (ELK, Loki) — single-user prototype
- Metrics/dashboards (Prometheus, Grafana) — YAGNI
- Distributed tracing (OpenTelemetry) — monolith
- Alerting/paging — one user, running locally
- Auto-merging troubleshooter PRs — require developer review
- Multi-turn bug-report interrogation — one question max
- Cross-session aggregation — sessions are independent
- Redesign of analysis chat — ChatPanel not modified
- Bug-report history persistence — session-scoped
