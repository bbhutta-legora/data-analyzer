# Change Spec: Runtime Observability

Branch-scoped artifact — remove upon merge to main.

---

## 1. What's changing and why

The application currently has no structured runtime diagnostics. When an LLM call produces wrong output, generated code crashes, or a user sees a bad chart, the only trace is scattered `logger.info()` calls in `main.py` and `llm.py`. Developers have no way to reconstruct what happened, and users have no way to report issues other than rephrasing their question.

This change implements the full observability strategy defined in `harness/OBSERVABILITY-STRATEGY.md`: a per-session context buffer that captures operations at system boundaries, a two-path bug-catching pipeline (system-detected exceptions + user-reported issues), a troubleshooter agent that diagnoses errors and generates fixes, and automated PR creation for systemic bugs.

The trigger is the observability strategy document itself — this is the implementation of a planned architectural feature.

---

## 2. Current behavior

### Session state (`backend/session.py`)
- `Session` dataclass holds all mutable state: DataFrames, conversation history, code history, exec namespace, ML workflow state.
- No context buffer field exists. No operation history is tracked.
- `SessionStore` provides create/get/delete. No hook points for buffer management.

### Error handling (`backend/main.py`)
- Individual endpoints catch expected errors (missing session → 404, invalid input → 400, parse failure → 400).
- **No top-level exception handler.** Unhandled exceptions produce FastAPI's default 500 with a stack trace.
- LLM errors in `/api/chat` are caught in `_attempt_chat_with_retries` (line ~543) and streamed back as SSE error events. After `MAX_CHAT_RETRIES` (1), the error is logged and sent to the user as-is.

### LLM calls (`backend/llm.py`)
- `call_llm_chat()` (line ~466) and `call_llm()` (line ~415) call Anthropic/OpenAI APIs.
- Response parsing in `parse_chat_response()` (line ~290) extracts JSON with code/explanation.
- Logging: `logger.warning` on parse failures, `logger.info` on call start/response receipt.
- No structured capture of inputs, outputs, or parsed results.

### Code execution (`backend/executor.py`)
- `execute_code()` (line ~197) runs LLM-generated code in a subprocess sandbox.
- Returns `{stdout, figures, error, dataframe_changed, new_dfs_pickle}`.
- No logging or context capture of what was executed or what it produced.

### File parsing (`backend/main.py`, lines ~89-114)
- `parse_dataframes_from_bytes()` parses CSV/Excel into DataFrames.
- Called by `/api/upload`. Failures are caught and return 400.
- No capture of parse results (shape, columns, dtypes).

### Data cleaning (`backend/clean.py`, `backend/main.py` lines ~678-750)
- `apply_cleaning_action()` dispatches to pure functions (drop_duplicates, fill_median, drop_missing_rows).
- `logger.info()` logs the action at the endpoint level.
- No capture of before/after state.

### User bug reporting
- Does not exist. No endpoint, no UI, no mechanism.

### Frontend (`frontend/src/`)
- Single-screen chat interface (ChatPanel) with header bar, scrollable messages, and input bar.
- No bug-report UI, no floating buttons, no secondary chat context.

### GitHub integration
- None. No GitHub API client, no tokens, no PR creation capability.

---

## 3. Desired behavior

### Context buffer
- `Session` gains a `context_buffer: list[ContextEntry]` field, initialized empty, capped at 20 entries (FIFO).
- `ContextEntry` is a dataclass with: timestamp, operation, input_actual, output_actual, success, error, metadata.
- Buffer is in-memory only — not persisted, discarded when session ends.

### Instrumentation at 4 system boundaries
- **LLM calls**: Every `call_llm_chat()` / `call_llm()` invocation creates a context entry with the user's question, raw LLM response, model, purpose, parse success, parsed code, and token usage.
- **Code execution**: Every `execute_code()` call creates a context entry with the full code, stdout/error output, namespace keys, figure count, execution time, and DataFrame change detection.
- **File parsing**: Every `parse_dataframes_from_bytes()` call creates a context entry with filename, resulting shape, columns with dtypes, and missing value counts.
- **Data cleaning**: Every `apply_cleaning_action()` call creates a context entry with the action, target columns, and before/after row counts, column lists, and dtypes.

### Bug-catching Path 1: System-detected errors
- A top-level FastAPI exception handler catches **any unhandled exception from any endpoint** — regardless of whether the error originated at an instrumented boundary (LLM call, code execution) or in our own deterministic code (a wrong `.get()` call, an `AttributeError` from an unexpected data shape, an `IndexError` in a list comprehension). The boundary instruments feed evidence into the buffer; the top-level handler is the trigger that fires on any unhandled error.
- It builds a `DiagnosisRequest` (error details + context buffer + conversation history + current DataFrame metadata + ML state) and calls `diagnose()`.
- `diagnose()` lives in `troubleshooter.py` (not `llm.py` — it serves the observability pipeline, not the user's analysis session). It calls `call_llm_chat()` from `llm.py` for the actual API transport, but prompt construction, classification logic, and the `DiagnosisRequest`/`Diagnosis` dataclasses all belong to the troubleshooter module.
- `diagnose()` classifies the error (transient / user_caused / systemic) and returns a `Diagnosis`.
- For transient/user_caused: returns a friendly user-facing message. Done.
- For systemic: returns the friendly message to the user immediately, then spawns a background task.
- Background task invokes a **managed agent** (Anthropic's hosted agent infrastructure) via the Anthropic SDK (`client.beta.agents` / `client.beta.sessions`). The managed agent has built-in tools (bash, read, write, edit, glob, grep) and runs in an Anthropic-managed cloud environment. It clones the repo, explores the codebase, generates a fix following the brownfield harness guidelines, writes a regression test, runs the test suite, and commits + pushes to a fix branch. The troubleshooter then opens a PR from the agent's committed changes.
- Each step degrades gracefully if secrets are missing (see Acceptance Criteria).

### Bug-catching Path 2: User-reported bugs
- New endpoint: `POST /api/bug-report` accepts `{session_id, message}`.
- Builds a `DiagnosisRequest` with `error_type="user_reported"` and the user's description as `error_message`.
- Feeds into the same troubleshooter pipeline as Path 1.
- Returns a short acknowledgment + optional single clarifying question.

### Frontend: Bug report widget
- A circular floating action button (~40px) positioned bottom-right of the chat screen, above the input bar.
- Clicking opens a compact chat widget (~340x380px) anchored to the bottom-right corner.
- Widget has its own header ("Report an Issue" + close button), scrollable message area, and text input.
- Messages are sent to `POST /api/bug-report` and responses displayed in the widget.
- Main analysis chat remains fully interactive underneath — no overlay, no dimming, no layout shift.
- Widget is a separate React component tree; it does not modify the existing ChatPanel.

### New module: `backend/troubleshooter.py`
- Owns the entire observability pipeline: diagnosis, fix-agent invocation, and PR creation.
- Contains `diagnose()`, `invoke_fix_agent()`, `create_fix_pr()`, and `handle_systemic_error()`.
- Contains all dataclasses: `ContextEntry`, `DiagnosisRequest`, `Diagnosis`.
- Diagnosis prompt template lives as a constant at the top of this file (per coding principle: "Keep all LLM prompts in `llm.py` or as constants at the top of the file where they're used").
- `diagnose()` calls `call_llm_chat()` from `llm.py` for the actual API call. This is a single LLM call for error classification — not agentic.
- `invoke_fix_agent()` uses the **Anthropic managed agent API** (`client.beta.agents` / `client.beta.sessions`). It creates a session with a pre-configured managed agent, sends the diagnosis as a user message, and polls for completion. The managed agent runs in Anthropic's cloud with built-in tools (bash, read, write, edit, glob, grep) — no custom tool implementations needed. The agent clones the repo, explores, fixes, tests, and commits autonomously.
- The managed agent is created once at application startup with a system prompt that includes the **brownfield coding guidelines from the harness**: invariant awareness, `harness/coding_principles.md` (explicit types, greppable names, verbose comments, error handling contracts), and `harness/TEST-STRATEGY.md` test patterns. This ensures generated PRs match codebase conventions.
- `create_fix_pr()` uses PyGithub to open a PR from the branch the managed agent committed to.
- `handle_systemic_error()` orchestrates the background pipeline: diagnose → invoke agent → open PR.

### Managed agent setup (one-time, at app startup)
- A managed agent is created via `client.beta.agents.create()` with the troubleshooter system prompt and the `agent_toolset` (bash, read, write, edit, glob, grep).
- A cloud environment is created via `client.beta.environments.create()` with `pytest` pre-installed and unrestricted networking (needed to clone the repo and push commits).
- Agent ID and environment ID are stored as module-level state in `troubleshooter.py`.
- If `ANTHROPIC_API_KEY` (for managed agent access) is not set, agent setup is skipped and the pipeline degrades gracefully (diagnosis only, no fix generation).

### New dependencies
- `PyGithub` added to `requirements.txt` for PR creation.
- No new dependency for the managed agent — uses the existing `anthropic` SDK (already a dependency) via `client.beta.agents` and `client.beta.sessions`.

### New environment variables
- `TROUBLESHOOTER_GITHUB_TOKEN` — repo access token for git push + PR creation. If missing, fix generation still runs but PR creation is skipped; diagnosis + agent output logged to console.
- The managed agent uses the same `ANTHROPIC_API_KEY` already configured for the app's LLM calls. No separate troubleshooter key needed — the managed agent API is part of the Anthropic platform.
- `TROUBLESHOOTER_REPO_URL` — the repo URL the managed agent clones into its environment. Required for fix generation; if missing, Phases 2-3 are skipped.

---

## 4. Acceptance criteria

1. **When** a session is created, **then** `session.context_buffer` is an empty list.
2. **When** an LLM call completes (success or failure), **then** a `ContextEntry` with operation="llm_call" is appended to the session's buffer with all metadata fields per the strategy doc.
3. **When** code is executed in the sandbox, **then** a `ContextEntry` with operation="code_execution" is appended with full code, stdout/error, namespace keys, figure count, execution time, and DataFrame change status.
4. **When** a file is uploaded and parsed, **then** a `ContextEntry` with operation="file_parse" is appended with filename, resulting shape, columns with dtypes, and missing values.
5. **When** a cleaning action is applied, **then** a `ContextEntry` with operation="data_clean" is appended with action, target columns, and before/after row counts, column lists, and dtypes.
6. **When** the buffer exceeds 20 entries, **then** the oldest entry is dropped.
7. **When** an unhandled exception reaches a user-facing endpoint, **then** the top-level handler catches it, calls `diagnose()`, and returns a friendly JSON error (not a stack trace) to the user.
8. **When** `diagnose()` classifies an error as transient or user_caused, **then** no background task is spawned.
9. **When** `diagnose()` classifies an error as systemic, **then** a background task creates a managed agent session, sends the diagnosis, and polls until the agent completes (explores, fixes, tests, commits). Then `create_fix_pr()` opens a PR from the agent's branch.
10. **When** `ANTHROPIC_API_KEY` is not set, **then** the entire troubleshooter pipeline is unavailable (no diagnosis, no fix generation). Unhandled exceptions still return a generic friendly message.
11. **When** `TROUBLESHOOTER_GITHUB_TOKEN` is not set, **then** the managed agent cannot clone/push, so Phases 2-3 are skipped; diagnosis is logged to console.
12. **When** `TROUBLESHOOTER_REPO_URL` is not set, **then** Phases 2-3 are skipped; diagnosis is logged to console.
13. **When** fix generation or PR creation fails, **then** the pipeline logs the failure and stops — no error propagates to the user.
14. **When** a user sends a message to `POST /api/bug-report`, **then** a `DiagnosisRequest` is built with `error_type="user_reported"` and processed through the same pipeline.
15. **When** a user sends a bug report, **then** the response is a short acknowledgment, with at most one clarifying question.
16. **When** the user clicks the FAB on the chat screen, **then** a compact bug-report chat widget opens in the bottom-right corner.
17. **When** the bug-report widget is open, **then** the main analysis chat remains fully interactive with no layout shift.
18. **When** a systemic bug produces a PR, **then** the PR body contains: diagnosis (classification, root cause, evidence), reproduction steps, fix description, and files changed. The PR is never auto-merged.
19. **When** the managed agent produces code, **then** the fix follows brownfield harness conventions: explicit types, verbose comments with cross-references, error handling contracts documented, and greppable names. Regression tests match existing test file patterns and conventions. This is enforced via the agent's system prompt, which includes the relevant harness principles.

---

## 5. Invariants to preserve

These behaviors must NOT change. Characterization tests will be written for any that lack coverage.

### API contracts
- `POST /api/upload` — request shape (multipart file + optional form fields), response shape (session_id, datasets metadata, summary), status codes (200, 400, 422).
- `POST /api/chat` — request shape (session_id, question, history), SSE response format (event types: chunk, metadata, error, done), status codes.
- `POST /api/clean` — request shape (session_id, action, column, dataset_name), response shape (updated metadata), status codes (200, 400, 404).
- `POST /api/clean/reset` — request/response shape, status codes.
- `POST /api/ml-step` — request shape, SSE response format, status codes.
- `GET /api/export/{session_id}` — response shape (.ipynb JSON), status codes.
- `GET /api/models` — response shape, status codes.
- `POST /api/validate-key` — request/response shape, status codes.
- `GET /api/health` — response shape.

### Error handling contracts
- Explicit 400 responses for invalid input (bad file type, empty file, oversized file, invalid action, missing session fields) must continue to return 400, not be swallowed by the top-level handler.
- Explicit 404 responses for missing sessions must continue to return 404.
- SSE error events in `/api/chat` and `/api/ml-step` must continue to stream error details to the client.
- The top-level exception handler must only catch exceptions that currently produce unhandled 500s — it must not intercept any currently-handled error path.

### Session behavior
- `SessionStore.create()` always succeeds and returns a valid session_id.
- `SessionStore.get()` returns `None` for unknown IDs (never raises).
- `SessionStore.delete()` returns `False` for unknown IDs (never raises).
- DataFrame isolation: working copies and originals are independent; mutations to one don't affect the other.
- `exec_namespace` is populated with sandbox libraries + `dfs` dict + `print`.

### LLM call behavior
- `call_llm_chat()` and `call_llm()` continue to call the correct provider SDK based on the `provider` argument.
- `parse_chat_response()` continues to return the same structured dict on success and the same error string on failure.
- Retry logic in `_attempt_chat_with_retries` continues to retry up to `MAX_CHAT_RETRIES` times.
- `generate_summary()` continues to work independently of the chat flow.

### Code execution behavior
- `execute_code()` continues to run code in a subprocess with timeout enforcement.
- Blocked builtins (`__import__`, `open`, `eval`, `exec`, `compile`, `globals`, `locals`) remain blocked.
- Figure capture, stdout capture, and DataFrame change detection continue to work.

### Data cleaning behavior
- Pure functions in `clean.py` (`drop_duplicates`, `fill_median`, `drop_missing_rows`) continue to produce the same transformations.
- `VALID_ACTIONS` set is unchanged.

### Frontend behavior
- The existing ChatPanel component renders and behaves identically — message display, input submission, SSE streaming, data summary, cleaning suggestion cards, ML wizard, code blocks, chart images.
- Header bar buttons (Reset, Build a Model, Export) remain functional.
- No layout shift or reflow of the existing UI when the bug-report widget is closed.

---

## 6. Out of scope

- **Persistent log storage** — context buffer is in-memory, session-scoped. No database, no file logging.
- **Log aggregation / search** (ELK, Loki) — single-user prototype.
- **Metrics / dashboards** (Prometheus, Grafana) — YAGNI.
- **Distributed tracing** (OpenTelemetry, Jaeger) — monolith.
- **Alerting / paging** — one user, running locally.
- **Auto-merging of troubleshooter PRs** — PRs require developer review.
- **Multi-turn bug-report interrogation** — one clarifying question max, then acknowledge.
- **Cross-session aggregation** — each session is independent.
- **Redesign of the existing analysis chat** — the ChatPanel component is not modified.
- **Bug-report chat history persistence** — bug chat is session-scoped like everything else.
