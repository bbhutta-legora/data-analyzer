# Smart Dataset Explainer — Observability Strategy

How bugs get caught, diagnosed, and fixed at runtime. This document is prescriptive — follow these patterns when adding error handling, LLM calls, or session operations.

---

## Philosophy

Tests catch bugs before deployment. But in an LLM-powered app, many bugs only surface at runtime — the model generates bad code, hallucinates column names, or produces output that's technically valid JSON but semantically wrong. No test suite can anticipate every combination of user data and natural-language question.

**Our approach: catch bugs at runtime through two paths, and turn each one into a PR for developers.**

| Path | Trigger | Example |
|------|---------|---------|
| **System-detected** | An exception reaches a user-facing boundary | `KeyError: 'revenue'` — LLM-generated code references a column that doesn't exist |
| **User-reported** | The user tells us something is wrong through the chat interface | "That chart is wrong — sales should be going up, not down" |

Both paths feed into the same troubleshooter agent, which diagnoses the issue, classifies it, and — for systemic bugs — opens a PR with a proposed fix. The user never sees the diagnosis or the code. Developers get the PR.

The infrastructure that makes this possible is a lightweight **context buffer** — a per-session, in-memory rolling window of recent operations. It's plumbing, not the strategy. The strategy is: **catch bugs from both directions and convert them into actionable fixes.**

---

## Principles

1. **Two input paths, one pipeline.** Whether the system throws an error or the user says "that's wrong," the troubleshooter receives the same structured context and produces the same structured output. Don't build two separate diagnostic systems.

2. **React, don't record.** Don't log for the sake of logging. The context buffer exists in memory so the troubleshooter has what it needs when something goes wrong. If nothing goes wrong, the buffer is never examined and is discarded when the session ends.

3. **The user reports bugs in the conversation, not a separate system.** The user is already in a chat interface. They shouldn't need to open a separate bug tracker, write an email, or screenshot an error. They just say what's wrong in the same chat. The system recognizes it and handles it.

4. **The user sees acknowledgment, never internals.** When a bug is detected — by either path — the user gets a simple, friendly message. They never see stack traces, context buffers, diagnoses, diffs, or PRs. That's all developer-facing.

5. **Session-scoped, not global.** Each session maintains its own context buffer. No cross-session aggregation, no central log store, no persistent infrastructure. The unit of bug-catching is one user's conversation.

6. **Instrument boundaries first, but catch everything.** The context buffer captures entries at system boundaries (LLM calls, code execution, file parsing) because that's where the most useful diagnostic context lives. But the troubleshooter itself activates on *any* unhandled exception — including bugs in our own deterministic code. The buffer gives the troubleshooter context about what led up to the error; the top-level exception handler ensures no error type is invisible.

---

## The Runtime Context Buffer

### What it is

A per-session, in-memory list of recent operations. Each entry is a lightweight dict capturing what happened at a system boundary. The buffer has a fixed max length; when full, the oldest entry is dropped.

### What an entry contains

Each entry captures one operation at a system boundary:

```python
@dataclass
class ContextEntry:
    timestamp: str              # ISO 8601, for ordering
    operation: str              # e.g. "llm_call", "code_execution", "file_parse", "data_clean"
    input_summary: str          # Brief description of what went in (NOT the full payload)
    output_summary: str | None  # Brief description of what came out (None if it hasn't completed)
    success: bool | None        # None while in-flight, True/False on completion
    error: str | None           # Error message + type if failed, None otherwise
    metadata: dict              # Operation-specific context (see per-operation guidance below)
```

### What it does NOT contain

- **Full LLM prompts or responses** — Too large. Summarize: "Asked for cleaning suggestions for 5 columns" / "Returned 3 suggestions in valid JSON."
- **Full dataframes or datasets** — Reference by shape and column names only.
- **API keys or credentials** — Never, under any circumstances.
- **User PII** — The buffer holds operation metadata, not user data content.

### Buffer sizing

Start with a max length of **20 entries**. This is enough to trace the chain of operations leading to most errors without holding the entire session history. Adjust based on experience — if the troubleshooter consistently needs more context, increase it; if most diagnoses only need the last 3–5 entries, decrease it.

```python
CONTEXT_BUFFER_MAX_LENGTH = 20
```

### Where it lives

The context buffer is a field on the session object in `session.py`. It is created when the session starts and garbage-collected when the session ends. It is never persisted to disk.

---

## What to Instrument

Capture context entries at these boundaries, in priority order:

### 1. LLM calls (highest priority)

Every call to the Anthropic/OpenAI API gets a context entry. This is the most common source of runtime failures (malformed responses, unexpected formats, refusals, rate limits).

**Metadata to capture:**
- `model`: Which model was called
- `purpose`: What the call was for ("analysis_query", "cleaning_suggestion", "code_generation")
- `prompt_summary`: One sentence describing what was asked (NOT the full prompt)
- `response_format`: What format was expected ("json", "code", "text")
- `parse_success`: Whether the response parsed into the expected format
- `token_usage`: Input/output token counts (useful for diagnosing truncation)

**Example entry:**
```python
{
    "operation": "llm_call",
    "input_summary": "Asked for Python code to visualize correlation matrix for 8 numeric columns",
    "output_summary": "Returned JSON with code field (47 lines) and explanation field",
    "success": True,
    "metadata": {
        "model": "claude-sonnet-4-20250514",
        "purpose": "analysis_query",
        "response_format": "json",
        "parse_success": True,
        "token_usage": {"input": 1820, "output": 645},
    },
}
```

### 2. Sandboxed code execution

Every `exec()` call in `executor.py` gets a context entry. LLM-generated code is the second most common failure point.

**Metadata to capture:**
- `code_summary`: First and last line of the code, plus line count (NOT the full code — it's in the session's code history already)
- `namespace_keys`: What variables were available in the execution namespace
- `had_figures`: Whether matplotlib figures were captured
- `stdout_length`: Length of captured stdout
- `execution_time_ms`: How long execution took (useful for diagnosing timeouts)

### 3. File upload and parsing

Dataset uploads involve format detection, encoding guessing, and pandas parsing — all of which can fail in surprising ways.

**Metadata to capture:**
- `filename`: Original filename
- `file_size_bytes`: Size of the uploaded file
- `detected_format`: csv, xlsx, etc.
- `resulting_shape`: (rows, cols) of the parsed DataFrame
- `column_types_summary`: e.g. "5 numeric, 3 object, 1 datetime"

### 4. Data cleaning operations

Cleaning steps transform the working dataframe. Capture what changed so the troubleshooter can trace data-related errors back to a cleaning step.

**Metadata to capture:**
- `cleaning_type`: e.g. "drop_column", "fill_missing", "convert_type"
- `target_columns`: Which columns were affected
- `rows_before`: Row count before
- `rows_after`: Row count after
- `shape_changed`: Whether the dataframe shape changed

---

## Bug-Catching Path 1: System-Detected Errors

### When it activates

The troubleshooter activates automatically when **any unhandled exception reaches a user-facing endpoint** — regardless of whether the error originated at a system boundary (LLM call, file parse) or inside our own deterministic code (a `.get()` on a list instead of a dict, an `AttributeError` from an unexpected data shape, a `StopIteration` from an empty collection).

Tests can't cover every input combination. Code that's "deterministic" can still be wrong for inputs we didn't anticipate. The troubleshooter catches what tests miss.

It does NOT activate for:

- Handled retries (e.g., LLM call fails, retry succeeds — no need to diagnose)
- Validation errors with obvious causes (e.g., "no file uploaded" — the user knows what happened)
- Expected edge cases already covered by explicit error messages (e.g., "session not found" 404s)

**Implementation:** A top-level exception handler (FastAPI exception handler or middleware) catches any unhandled exception that would otherwise produce a 500. It passes the error and the session's context buffer to the troubleshooter before returning a friendly error to the user. Individual `except` blocks in route handlers still handle expected errors (missing session, invalid input) — the top-level handler catches everything else.

**Activation points (in priority order):**
1. **Top-level exception handler** — catches any unhandled exception from any endpoint. This is the safety net that ensures nothing slips through.
2. **After LLM retries exhausted** — the retry loop in `_attempt_chat_with_retries` gives up and the error is about to be streamed to the user.
3. **After sandboxed code execution fails** — the executor returns an error that the user can't self-diagnose.

### What it receives

The troubleshooter gets a **diagnosis request** containing:

1. **The error** — Exception type, message, and the immediate traceback (just the relevant frames, not the full stack)
2. **The context buffer** — The last N entries from the session's context buffer
3. **The current operation** — What the system was trying to do when the error occurred
4. **Session summary** — Dataset shape, column names, conversation turn count (NOT the full conversation history or dataframe contents)

```python
@dataclass
class DiagnosisRequest:
    error_type: str
    error_message: str
    traceback_summary: str          # Last 3-5 frames, not full trace
    context_buffer: list[dict]      # Recent ContextEntry dicts
    current_operation: str          # What was being attempted
    session_summary: dict           # Shape, columns, turn count
```

### Error classification

Not every runtime error is a code bug. The troubleshooter's first job is to classify the error before deciding what to do:

| Classification | Meaning | Example | Action |
|---------------|---------|---------|--------|
| **Transient** | Temporary external failure | Rate limit, network timeout, LLM refusal on one specific input | Retry or return a user-friendly message. No PR. |
| **User-caused** | The user's input or data triggered a predictable edge case | Empty dataset, unsupported file format, ambiguous question | Return a helpful error message guiding the user. No PR. |
| **Systemic (boundary)** | A flaw in how we interact with external systems | Bad prompt construction that causes the LLM to hallucinate column names, missing JSON parse validation | Diagnose, generate a fix, open a PR. |
| **Systemic (internal)** | A bug in our own deterministic code that tests didn't catch | `AttributeError` because `parse_chat_response` calls `.get()` on a list, `StopIteration` from an empty dataframe dict | Diagnose, generate a fix, open a PR. These are high-confidence bugs — our code is unambiguously wrong. |

Both **systemic** classifications produce a PR. The distinction matters for the diagnosis: boundary bugs need prompt or integration fixes; internal bugs need code fixes and probably a new test case to prevent regression. The troubleshooter must include its classification and reasoning — a developer reviewing the PR should be able to see why the troubleshooter considered this a code-level bug rather than a transient or user-caused issue.

### What it produces

The troubleshooter has two distinct outputs that go to different audiences:

**1. User-facing (immediate):** A simple, friendly error message. The user never sees the diagnosis, the context buffer, stack traces, or proposed code fixes. Examples:
- "Something went wrong analyzing your data. Try rephrasing your question."
- "We had trouble parsing that file. Make sure it's a valid CSV or Excel file."

**2. Developer-facing (PR for systemic errors):** When the troubleshooter classifies an error as systemic, it opens a pull request containing:

- **PR title:** One-line summary of the bug (e.g., "Fix: LLM prompt doesn't constrain column references to actual dataset columns")
- **PR body — Diagnosis section:**
  - What went wrong (the error and its immediate cause)
  - Why it happened (root cause analysis from the context buffer)
  - Evidence (which context buffer entries support the diagnosis)
  - Classification reasoning (why this is systemic, not transient or user-caused)
- **PR body — Reproduction section:**
  - The conditions that triggered the error (dataset shape, user question pattern, conversation state)
  - How a developer could reproduce it
- **PR diff — The proposed fix:**
  - The actual code changes the troubleshooter believes will prevent the error class

```python
@dataclass
class Diagnosis:
    classification: str     # "transient", "user_caused", or "systemic"
    classification_reason: str  # Why this classification
    summary: str            # One sentence: what went wrong
    likely_cause: str       # One paragraph: why it probably happened
    evidence: list[str]     # Which context buffer entries support the diagnosis
    user_message: str       # Friendly message shown to the user
    proposed_fix: ProposedFix | None  # None for transient/user-caused errors

@dataclass
class ProposedFix:
    description: str        # Plain-English description of the fix
    files_changed: list[str]  # Which files the fix touches
    diff: str               # The actual code diff
    reproduction_steps: str # How to reproduce the original error
```

**Example — systemic error producing a PR:**

```
classification: "systemic"
classification_reason: "The LLM prompt includes column names in the system message, but
  does not instruct the model to ONLY use those columns. This will reproduce for any user
  whose question mentions a concept that maps to a plausible-sounding column name."

summary: "LLM generated code referencing column 'revenue' which doesn't exist in the dataset."

likely_cause: "The user asked 'show me revenue trends' but the dataset columns are
  ['date', 'sales', 'region', 'units']. The prompt provided column names but didn't
  constrain the LLM to use only those names. The LLM inferred 'revenue' from the
  user's question."

evidence:
  - "Context entry 18: llm_call for analysis_query — response code references 'revenue'"
  - "Context entry 15: file_parse — columns: ['date', 'sales', 'region', 'units']"

user_message: "Something went wrong analyzing your data. Try rephrasing your question
  using the exact column names from your dataset."

proposed_fix:
  description: "Add explicit constraint to analysis prompt template: instruct the model
    to ONLY reference columns from the provided column list, and to ask the user for
    clarification if their question doesn't map to an existing column."
  files_changed: ["backend/llm.py"]
  diff: "<the actual diff>"
  reproduction_steps: "Upload a dataset with columns ['date', 'sales', 'region', 'units'].
    Ask 'show me revenue trends'. The generated code will reference df['revenue'],
    causing a KeyError."
```

**Example — transient error, no PR:**

```
classification: "transient"
classification_reason: "Anthropic API returned 429 rate limit. This is an external
  service constraint, not a code bug."

summary: "LLM API call rate-limited."
user_message: "The AI service is temporarily busy. Please try again in a moment."
proposed_fix: None
```

### Implementation approach

The troubleshooter is a function in `llm.py` (following the AI Logic Isolation principle from `coding_principles.md`). It makes a single LLM call with a diagnostic prompt. It is NOT a long-running agent, autonomous loop, or separate service. One error → one diagnosis → optionally one PR.

The workflow:

1. Error hits a user-facing boundary in `main.py`
2. `main.py` calls the troubleshooter with the `DiagnosisRequest`
3. Troubleshooter makes one LLM call, returns a `Diagnosis`
4. `main.py` returns `diagnosis.user_message` to the user (friendly, no internals)
5. If `diagnosis.classification == "systemic"` and `diagnosis.proposed_fix` is not None, a background task opens a PR on the project repo with the diagnosis and diff
6. The PR is assigned to the development team for review — the fix is never auto-merged

**The user never sees step 5 or 6.** From their perspective, they got a helpful error message. The PR is a developer-to-developer artifact.

Keep the diagnostic prompt simple and stable. It receives the structured `DiagnosisRequest` and returns the structured `Diagnosis`. No tool use, no multi-turn reasoning — just pattern matching on the context buffer plus code generation for the fix.

---

## Bug-Catching Path 2: User-Reported Bugs

### The problem this solves

Not every bug throws an exception. The LLM might generate code that runs successfully but produces a wrong chart, a misleading summary, or a nonsensical cleaning suggestion. From the system's perspective, everything worked. From the user's perspective, the output is broken.

Today the user has no way to report this except to rephrase their question and hope for better. That wastes the signal — the user knows something is wrong but the system discards that knowledge.

### How it works

The app provides a **separate bug report chat**, distinct from the main analysis conversation. This could be a side panel, a tab, or a toggle — the exact UI is a frontend design decision. The important architectural choice is: **the bug chat is a separate conversation context that shares the same session's context buffer.**

The user switches to the bug chat and describes what's wrong in natural language:

- "That chart is wrong — sales should be going up, not down"
- "This correlation doesn't make sense, those columns are unrelated"
- "The cleaning suggestion would delete half my data"
- "It's showing me data for the wrong column"

### Why a separate chat, not intent classification

Having a dedicated bug chat means every message in it is a bug report — no intent classification needed. This avoids:

- **False positives:** "that doesn't look right" in the main chat being treated as a bug report when the user just wants to refine their question
- **False negatives:** A genuine bug report being treated as a follow-up analysis question
- **Prompt complexity:** The analysis LLM doesn't need to handle a `"bug_report"` intent category alongside its existing responsibilities

The main analysis chat stays focused on analysis. The bug chat stays focused on bugs. Clean separation of concerns.

### What the troubleshooter receives for user-reported bugs

The same `DiagnosisRequest` structure, but populated differently:

```python
DiagnosisRequest(
    error_type="user_reported",
    error_message="That chart is wrong — sales should be going up, not down",
    traceback_summary="",               # No traceback — no exception was thrown
    context_buffer=session.context_buffer,  # Same rolling buffer
    current_operation="user_bug_report",
    session_summary={...},              # Same session summary as system-detected path
)
```

The troubleshooter uses the context buffer to reconstruct what happened: what data was loaded, what the user asked, what the LLM generated, what code was executed, and what output was produced. It then compares the user's complaint against that chain to diagnose the issue.

### What the user sees

In the bug chat, the user gets a short acknowledgment after submitting their report:

- "Thanks for flagging that. We've noted the issue and our team will look into it."

The bug chat can also ask a brief clarifying question if the user's report is vague — but only one follow-up, not a back-and-forth interrogation:

- "Got it. Just to make sure I understand — were you expecting the sales numbers to increase over time, or were they showing the wrong column entirely?"

The acknowledgment is brief. The system doesn't explain what it diagnosed, show a ticket number, or promise a timeline. The user's job is to tell us what's wrong — the system takes it from there. The main analysis chat is unaffected and the user can continue working in it.

### The same pipeline, different input

After intent classification routes the message to the troubleshooter, the rest of the pipeline is identical to system-detected bugs:

1. Troubleshooter receives `DiagnosisRequest` (with user's description instead of an exception)
2. Classifies: transient / user-caused / systemic
3. For systemic: generates diagnosis + proposed fix → opens PR
4. User gets acknowledgment message (never the diagnosis or code)

The key difference: user-reported bugs are **more likely to be systemic**. When a user says "the output is wrong," it usually means the LLM prompt or the code generation logic needs improvement — not that there was a transient API failure. The troubleshooter should weight toward `systemic` classification for user-reported bugs, but still classify as `user_caused` when the user's expectation is unreasonable given their data (e.g., "show me revenue trends" when no revenue column exists — that's guidance, not a code fix).

### What NOT to include in user-reported bug handling

- **A form-based bug reporter** (modal with required fields, dropdowns, severity selectors) — the chat is the interface, natural language is the format
- **A ticketing system** — PRs are the tickets
- **Status updates to the user** ("your bug is being worked on") — the user doesn't track bugs, developers do
- **Multi-turn interrogation** — one clarifying question at most, then acknowledge and process. The context buffer already has the reproduction steps; the user's description adds the "what's wrong" that the system can't infer on its own

---

## What NOT to Build

This is a prototype. The following are explicitly out of scope:

| Don't build | Why not |
|------------|---------|
| Persistent log storage | Sessions are ephemeral. Logs die with the session. YAGNI. |
| Log aggregation / search (ELK, Loki, etc.) | No multi-user, no production deployment. |
| Metrics / dashboards (Prometheus, Grafana, etc.) | Single-user prototype. Look at the console. |
| Distributed tracing (OpenTelemetry, Jaeger, etc.) | Monolith. No services to trace between. |
| Alerting / paging | One user, running locally. They'll see the error. |
| Auto-merging of troubleshooter PRs | The troubleshooter proposes fixes — a developer must review and merge. Never auto-merge generated code. |
| Background health checks | The user is the health check. If it's broken, they'll tell you. |

If the prototype graduates to production, revisit these decisions. Until then, they are YAGNI.

---

## Integration With Existing Harness

### Relationship to TEST-STRATEGY.md

Tests verify behavior is correct before deployment. The troubleshooter diagnoses behavior that's incorrect at runtime — typically caused by non-deterministic LLM outputs or unexpected user data that tests couldn't anticipate.

They are complementary:
- A test catches "LLM JSON parsing breaks when code fences are present" → fix the parser before deployment.
- Path 1 (system-detected) catches "LLM referenced a column that doesn't exist" → diagnoses the root cause, opens a PR with a fix, returns a friendly error to the user.
- Path 2 (user-reported) catches "The chart shows sales going down but they should be going up" → reconstructs the operation chain from the context buffer, diagnoses whether the prompt, the code generation, or the data transformation is at fault, opens a PR with a fix. The user gets "Thanks, we've noted this" — nothing more.

### Relationship to code_review_patterns.md §16 (Logging)

The logging review patterns still apply — when you DO log (e.g., the troubleshooter's diagnosis output), it should be structured and contextual per §16. The difference is that most runtime context now flows through the buffer and troubleshooter rather than through scattered `logger.info()` calls.

**Keep standard `logger.error()` and `logger.warning()` calls** for:
- Application startup/shutdown events
- Configuration issues (missing env vars, invalid settings)
- Unrecoverable errors that crash the process

**Route through the context buffer** instead of logging for:
- Per-request operation tracking
- LLM call metadata
- Execution results
- Data transformation steps

### Execution plan integration

When implementing features that touch system boundaries (LLM calls, execution, file I/O), Phase C (Implementation) should include adding context buffer entries at those boundaries. Phase E (Code Review) should verify:

1. Every new LLM call has a context entry with the metadata fields listed above
2. Every new error handler at a user-facing boundary triggers the troubleshooter
3. No full payloads (prompts, responses, dataframes) are stored in the buffer — summaries only
