# Smart Dataset Explainer — Architecture

## 1. System Overview

A monorepo containing a React frontend and a Python backend. The frontend handles the chat UI and user interactions. The backend manages LLM calls, sandboxed code execution, session state, and notebook export. Communication uses REST for standard operations and SSE for streaming LLM responses.

```
dataset_analyzer/
├── frontend/          # React (Vite + TypeScript)
├── backend/           # FastAPI (Python)
├── architecture.md
├── PRD.md
└── README.md
```

## 2. Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Frontend framework | React + TypeScript (Vite) | Component-based; mature ecosystem for chat UIs |
| Frontend state | Zustand | Lightweight; simpler than useReducer+Context for cross-component state |
| Backend framework | FastAPI | Async-native; first-class SSE support via `StreamingResponse` |
| LLM integration | Direct provider SDK (OpenAI / Anthropic) | No framework overhead; full control over prompts and retries |
| Code execution | `exec()` with restricted globals | In-process; no serialization overhead; simplest sandbox for a prototype |
| Charts | matplotlib / seaborn (server-side) | Figures captured as base64 PNG; same code works in exported notebooks |
| Testing | pytest (backend), Vitest (frontend) | Standard tooling for each ecosystem |
| Logging | Python `logging`, structured format | Human-readable traces for debugging |

The most technically demanding operation is sandboxed execution of arbitrary LLM-generated Python code. This anchored the decision to keep the backend in Python and use in-process `exec()` — avoiding serialization, container overhead, or cross-process dataframe transfer.

## 3. Backend Architecture

### 3.1 Module Structure

Six deep modules with simple interfaces. No sub-packages, no abstract base classes.

```
backend/
├── main.py              # FastAPI app, route definitions, CORS
├── session.py           # Session store, session lifecycle, state model
├── providers.py         # Supported providers, curated model catalog, validation model
├── llm.py               # Prompt construction, LLM API calls, response parsing
├── executor.py          # Sandboxed exec(), figure capture, result packaging
├── exporter.py          # Jupyter notebook (.ipynb) generation
├── sandbox_libraries.py # Single source of truth for exec namespace libraries
├── requirements.txt
└── tests/
```

### 3.2 Module Responsibilities

**`main.py`** — FastAPI application. Defines all HTTP endpoints and the SSE streaming endpoint. Wires together the other modules. Handles CORS, file upload parsing, and request validation. Owns the retry orchestration loop (`_attempt_chat_with_retries` / `_single_chat_attempt`) — `llm.py` builds retry prompts but `main.py` decides when to retry and how many times (`MAX_CHAT_RETRIES = 1`).

**`providers.py`** — Single source of truth for LLM provider configuration. Defines `SUPPORTED_PROVIDERS`, `ProviderLiteral`, `AVAILABLE_MODELS` (a curated 3-tier catalog per provider: Frontier / Balanced / Fast), `get_default_model()`, and `ANTHROPIC_VALIDATION_MODEL`. The frontend fetches model data via `GET /api/models` rather than hardcoding it.

**`session.py`** — Manages an in-memory dict of sessions keyed by session ID (UUID). Each session holds:
- `dataframes_original`: immutable snapshots of all uploaded DataFrames, keyed by name (e.g. `{"sales": df, "costs": df}`)
- `dataframes`: the current working copies, keyed by name; mutated by cleaning operations
- `conversation_history`: list of `{role, content}` messages for LLM context
- `code_history`: list of `{code, explanation, result}` entries for notebook export
- `exec_namespace`: the Python namespace dict used by the sandbox
- `original_filename`: the uploaded file's name (e.g. `"sales.csv"`); used by `exporter.py` for the data-loading cell and the download filename
- `api_key`: the user's LLM API key (held in memory only)
- `provider`: the provider the user selected (`"openai"` or `"anthropic"`)
- `model`: the specific model the user selected (e.g. `"gpt-5.4-mini"`)

For CSV uploads, `dataframes` contains a single entry keyed by the filename stem. For multi-sheet Excel uploads, it contains one entry per sheet. Each DataFrame is independently copied at creation time so mutations to one cannot affect others or their originals.

Sessions are created on file upload and discarded on explicit close or server restart. No persistence.

**`llm.py`** — Constructs prompts that include dataset metadata (column names, dtypes, shape, sample rows) and conversation history. Sends requests to the LLM API. Parses the structured JSON response into a typed object with `code`, `explanation`, and optional `cleaning_suggestions` fields. The system prompt instructs the LLM to proactively surface data quality issues relevant to the current question.

Key functions (Step 8):
- `build_chat_system_prompt(dataframes)` — builds the chat system prompt with dataset metadata, libraries, and response format instructions
- `build_chat_messages(question, conversation_history)` — builds the messages array (history + new question); system prompt is separate because OpenAI and Anthropic handle it differently
- `parse_chat_response(raw)` — parses JSON response into `{code, explanation, cleaning_suggestions}`
- `truncate_history(history, max_tokens)` — sliding-window truncation dropping oldest messages first; always preserves the most recent message; uses word_count * 1.3 token estimation
- `call_llm_chat(system_prompt, messages, api_key, provider, model)` — multi-turn LLM call dispatching to provider-specific helpers that handle system prompt differences (OpenAI: system message in array; Anthropic: separate `system` parameter)

**`executor.py`** — Runs LLM-generated code via `exec()` in a restricted namespace. The namespace is pre-populated with `pandas`, `numpy`, `matplotlib`, `seaborn`, `sklearn`, and `dfs` — a dict of all session DataFrames keyed by name. Captures matplotlib figures as base64 PNG by hooking `plt.savefig()` to a bytes buffer. Captures printed output and expression results. Returns a structured result object with `stdout`, `figures` (list of base64 strings), `error` (if any), and `dataframe_changed` flag.

**`exporter.py`** — Builds a Jupyter notebook (`.ipynb` JSON) from the session's code history. Each entry becomes a code cell + a markdown cell (for the explanation). Adds a header cell with import statements and a cell that loads the dataset. The exported notebook is self-contained and runnable.

### 3.3 Request Flow

**Chat question (SSE):**
1. Frontend sends user question + session ID via POST
2. `main.py` looks up session in `session.py`
3. `llm.py` constructs prompt with dataset context + conversation history, calls LLM API
4. `executor.py` runs the generated code in the session's namespace
5. **If any step fails** (LLM API error, JSON parse error, execution error, or timeout), `main.py` retries once via `_attempt_chat_with_retries`: `llm.py`'s `build_retry_messages` constructs a new prompt including the failed code and error traceback, then `_single_chat_attempt` runs the full cycle again. Timeout errors include extra guidance asking the LLM to generate simpler code.
6. Response streams to frontend via SSE (explanation text)
7. Execution results (figures, tables, stdout) sent as a final SSE event
8. If the LLM response includes `cleaning_suggestions`, these are sent as a separate SSE event for the frontend to render as interactive cards
9. Session's conversation history and code history updated with the **final outcome only** — intermediate failures are not recorded, keeping history clean for future LLM context
10. If all attempts fail, the frontend shows a friendly error message with a collapsible "Show details" toggle for the raw error

**File upload (REST):**
1. Frontend POSTs file (CSV/Excel)
2. `main.py` validates extension, size, and non-emptiness — returns structured `{"error": "<type>", "detail": "<message>"}` on failure (400/413)
3. `main.py` parses file into `dict[str, pd.DataFrame]` — one entry per CSV stem, one entry per Excel sheet
4. `session.py` creates a new session storing all DataFrames
5. `llm.py` generates the initial summary, suggested questions, and initial cleaning suggestions (Step 7)
6. Response returned as JSON with `session_id` and `datasets` metadata per DataFrame

**Data cleaning confirmation (REST):**
1. Frontend POSTs the user's cleaning decision (e.g., "drop duplicates")
2. `executor.py` runs the cleaning code on the session's dataframe
3. `llm.py` re-evaluates data quality and returns any follow-up cleaning suggestions
4. Updated stats + any new suggestions returned as JSON

**Export (REST):**
1. Frontend requests notebook download
2. `exporter.py` builds `.ipynb` from session's code history
3. File returned as a download response

## 4. Frontend Architecture

### 4.1 Structure

```
frontend/
├── src/
│   ├── App.tsx              # Top-level layout, screen routing
│   ├── store.ts             # Zustand store (session, messages, UI state)
│   ├── api.ts               # Backend API client (REST + SSE helpers)
│   ├── components/
│   │   ├── ApiKeyInput.tsx   # BYOK setup screen
│   │   ├── FileUpload.tsx    # Upload + sheet picker
│   │   ├── ChatPanel.tsx     # Message list + input
│   │   ├── MessageBubble.tsx # Single message (explanation, code toggle, charts)
│   │   ├── DataSummary.tsx   # Initial summary display
│   │   ├── CleaningPrompt.tsx# Confirmation UI for cleaning suggestions
│   │   └── HelpModal.tsx     # Help overlay
│   └── main.tsx
├── package.json
├── vite.config.ts
├── tsconfig.json
└── tests/
```

### 4.2 State Shape (Zustand)

```typescript
interface AppState {
  sessionId: string | null
  apiKey: string | null
  provider: 'openai' | 'anthropic' | null
  model: string | null        // e.g. "gpt-5.4-mini", "claude-sonnet-4-6"
  messages: Message[]
  isStreaming: boolean
  datasetInfo: DatasetInfo | null
  currentScreen: 'setup' | 'upload' | 'chat'
}
```

### 4.3 Key UI Behaviors

- **Streaming:** SSE connection reads tokens as they arrive, appends to the current assistant message in the store. A final event delivers execution results (figures, tables).
- **Code toggle:** Each assistant message stores the generated code. Hidden by default, shown via a "Show code" button. Rendered with syntax highlighting.
- **Suggested questions:** Displayed as clickable chips after the initial summary. Clicking one sends it as a chat message.
- **Cleaning confirmations:** Rendered as interactive cards with buttons for each option (e.g., "Drop duplicates" / "Keep them").
- **Charts:** Rendered as `<img>` tags from base64 PNG data.
- **Error display:** Error messages show a friendly wrapper ("I couldn't execute the analysis. Try rephrasing your question or being more specific.") with a collapsible "Show details" toggle that reveals the raw error — mirroring the "Show code" toggle pattern used for generated code.

## 5. Communication Protocol

| Operation | Method | Path | Format |
|-----------|--------|------|--------|
| Get available models | GET | `/api/models` | JSON |
| Validate API key | POST | `/api/validate-key` | JSON |
| Upload dataset | POST | `/api/upload` | multipart/form-data → JSON |
| Chat question | POST | `/api/chat` | JSON → SSE stream |
| Apply cleaning action | POST | `/api/clean` | JSON |
| Export notebook | GET | `/api/export/{session_id}` | `.ipynb` file download |

SSE event types for the chat stream:
- `explanation`: streamed text tokens
- `result`: execution output (figures, tables, stdout)
- `cleaning_suggestions`: array of suggested fixes, each with a description and options
- `error`: execution failure with plain-English description
- `done`: stream complete

## 6. Sandboxed Execution

The `exec()` namespace is pre-populated with:
- `pd` (pandas), `np` (numpy), `plt` (matplotlib.pyplot), `sns` (seaborn), `sklearn`
- `dfs` — a `dict[str, pd.DataFrame]` of all session DataFrames keyed by name. LLM-generated code accesses DataFrames as `dfs["name"]`. This is the single access pattern for all upload types — one DataFrame or many.
- `print` — captured to a string buffer

Restricted by removing: `__import__`, `open`, `eval`, `exec`, `compile`, `__builtins__` (replaced with a safe subset). This prevents filesystem access, network calls, and dynamic imports.

Figure capture: after `exec()`, check `plt.get_fignums()`. For each open figure, save to a `BytesIO` buffer as PNG, encode as base64, then `plt.close()`.

Resource limits: execution timeout via `multiprocessing.Process` + `process.kill()` — cross-platform, no `signal.SIGALRM`.

## 7. LLM Prompting

The system prompt includes:
- Role definition (data analysis assistant for junior data scientists)
- Response format instructions (return JSON with `code`, `explanation`, and optional `cleaning_suggestions` fields)
- Instruction to proactively flag data quality issues relevant to the current question
- Available libraries and the variable name for the dataframe (`df`)
- Dataset metadata (columns, dtypes, shape, sample rows, missing value counts)

Conversation history is sent as prior messages to maintain context.

**Error retry flow:** All error types are retryable — LLM API errors, JSON parse failures, execution errors, and timeouts. Retry orchestration lives in `main.py` (`_attempt_chat_with_retries`), not `llm.py`. On failure, `llm.py`'s pure function `build_retry_messages` constructs a new messages array containing the conversation history plus a user message with the original question, failed code, and error traceback. For timeout errors, `TIMEOUT_RETRY_GUIDANCE` is appended asking the LLM to generate simpler, faster code. `main.py` re-runs the full LLM-call-parse-execute cycle up to `MAX_CHAT_RETRIES` (1) times. If all attempts fail, the error is returned to the user. Conversation history records only the final successful outcome — intermediate failures are never appended.

## 8. Observability

- **Logging:** structured Python `logging` with human-readable format. Log at INFO level: every LLM request/response (prompt length, response length, latency), every code execution (code snippet, success/failure, execution time), session lifecycle events. Log at ERROR level: execution failures with full tracebacks, LLM API errors.
- **Backend tests:** pytest. Unit tests for `executor.py` (code execution, figure capture, restricted namespace). Unit tests for `llm.py` (prompt construction, response parsing). Integration tests for the full chat flow (question → LLM → execute → response).
- **Frontend tests:** Vitest. Component tests for key interactions (file upload, message rendering, code toggle, cleaning confirmation).

## 9. Decisions Log

| # | Decision | Choice |
|---|----------|--------|
| 1 | Code execution sandboxing | `exec()` with restricted globals |
| 2 | Frontend framework | React (Vite + TypeScript) |
| 3 | Backend framework | FastAPI |
| 4 | Frontend-backend communication | REST + SSE for streaming |
| 5 | Session state management | In-memory server-side dict keyed by session ID |
| 6 | LLM integration | Direct provider SDK (no framework) |
| 7 | LLM response structure | Structured JSON (`{code, explanation}`) |
| 8 | Chart rendering | Server-side matplotlib/seaborn → base64 PNG |
| 9 | Repo structure | Monorepo with `frontend/` and `backend/` |
| 10 | Backend module design | 6 deep modules: main, session, providers, llm, executor, exporter + sandbox_libraries |
| 14 | LLM provider support | OpenAI and Anthropic (both built in from Step 6; not deferred) |
| 15 | Model selection | Curated 3-tier catalog per provider (Frontier/Balanced/Fast); served via `GET /api/models`; `providers.py` is single source of truth |
| 11 | Frontend state | Zustand |
| 12 | Testing | pytest + Vitest |
| 13 | Logging | Python `logging`, structured, human-readable |
| 16 | Error retry orchestration | Retry loop in `main.py`, pure retry-prompt builder in `llm.py`; all error types retryable; conversation history records only final outcomes |
