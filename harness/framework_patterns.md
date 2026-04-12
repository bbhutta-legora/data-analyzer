# Framework Patterns

Framework-specific patterns, gotchas, and best practices learned through implementation. Organized by framework/technology.

For general coding principles that apply regardless of framework, see `architectural_principles.md`.

---

## Anthropic / LLM Integration

### Handling JSON Responses

LLMs non-deterministically wrap JSON responses in markdown code fences, even when explicitly instructed to return "JSON format". Always strip code fences before parsing.

**Critical:** Do not anchor the regex to end-of-string (`$`) — the LLM may append trailing prose after the closing fences.

```python
import re

# GOOD: Extracts first code-fenced block, allows trailing content
_CODE_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)

def strip_code_fences(text: str) -> str:
    """Strip markdown code fences if present, return inner content."""
    match = _CODE_FENCE_RE.match(text)
    return match.group(1).strip() if match else text

# Usage
raw_response = call_llm(prompt)
cleaned = strip_code_fences(raw_response)
parsed = json.loads(cleaned)  # Now safe to parse
```

#### ❌ Anti-Pattern: End-of-string anchor

```python
# BAD: Requires fences to span entire response; fails when LLM adds prose
_CODE_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)
#                                                                        ^^^ problematic anchor

# LLM response example:
# ```json
# {"code": "df.describe()", "explanation": "Summary statistics"}
# ```
#
# Here is a brief note about the analysis...
#
# → Regex fails to match due to trailing prose
```

#### ❌ Anti-Pattern: Direct JSON parsing
```python
# BAD: Will fail ~40% of the time when LLM wraps in code fences
response = await client.messages.create(...)
parsed = json.loads(response.content[0].text)  # Fails with "Expecting value: line 1 column 1"
```

#### ✓ Pattern: Strip before parsing
```python
# GOOD: Handle code fence wrapping
response = await client.messages.create(...)
cleaned = strip_code_fences(response.content[0].text)
parsed = json.loads(cleaned)
```

**Why this matters:** The error "Invalid JSON: Expecting value: line 1 column 1 (char 0)" typically means the response starts with backticks not that it's empty. Always inspect raw LLM output when debugging parse errors. This is especially relevant in `llm.py` where the structured `{code, explanation, cleaning_suggestions}` response is parsed.

---

### Prompt Engineering for Edge Cases

When LLM input may contain empty strings or placeholder-like content (e.g., all-null columns, zero-row datasets, `[attached]`, `[TBD]`, `______`), the model may interpret these as instructions rather than literal content, returning prose/clarification instead of structured output.

#### ✓ Pattern: Explicit delimiters and instructions
```yaml
analysis_prompt: |
  Analyze the following dataset and return a JSON response.
  
  DATASET METADATA (exact content, columns may have null values):
  """
  {dataset_metadata}
  """
  
  USER QUESTION:
  """
  {user_question}
  """
  
  IMPORTANT: Always respond with valid JSON only. Never ask clarifying questions.
  Even if columns appear empty or the dataset seems incomplete, respond based on what is shown.
```

#### ❌ Anti-Pattern: Ambiguous content boundaries
```yaml
# BAD: Model may interpret empty column data as an instruction, not content
analysis_prompt: |
  Dataset: {dataset_metadata}
  Question: {user_question}
  
  Respond in JSON format:
```

**Why this matters:** When the model sees a column with all-null values or a dataset with 0 rows, it may ask for clarification ("I don't see any data...") instead of returning the requested JSON. Explicit delimiters (triple quotes) and clear instructions ("Never ask clarifying questions") prevent this.

---

### Template String Escaping

When using Python's `str.format()` for prompt templates that contain literal curly braces (e.g., JSON examples in the response format instructions), escape them with double braces `{{` and `}}`.

#### ❌ Anti-Pattern: Unescaped braces in templates
```python
# WILL FAIL with KeyError when used with str.format()
prompt_template = """
  Respond in JSON format:
  {
    "code": "<python code>",
    "explanation": "<explanation>"
  }
  Question: {user_question}
"""
prompt_template.format(user_question=question)  # KeyError: 'code'
```

#### ✓ Pattern: Escaped braces for literals
```python
# GOOD: double braces become single braces in the formatted output
prompt_template = """
  Respond in JSON format:
  {{
    "code": "<python code>",
    "explanation": "<explanation>"
  }}
  Question: {user_question}
"""
prompt_template.format(user_question=question)  # Works correctly
```

**Why this matters:** Python's `str.format()` interprets `{...}` as a placeholder. The response format instructions sent to the LLM in `llm.py` contain literal JSON examples with curly braces — these will cause `KeyError` at runtime if not escaped. The error may not surface until the template is actually formatted with a real question.

#### ⚠️ Only applies to `.format()` and f-strings

`{{` is only an escape sequence inside f-strings and `.format()` calls. In a plain string constant passed directly to the API, `{{` sends two literal characters to the LLM.

```python
# Plain string constant — single braces are correct
SYSTEM_PROMPT = """Return JSON: {"code": "...", "explanation": "..."}"""

# f-string — double braces produce literal braces
SYSTEM_PROMPT = f"""Return JSON: {{"code": "{value}", "explanation": "..."}}"""
```

---

### Template and Formatter Coupling

When the LLM response schema evolves (e.g., adding `cleaning_suggestions` to the `{code, explanation}` response), the prompt template and the response parser in `llm.py` must be updated **in the same step**.

#### ❌ Anti-Pattern: Add schema field without updating parser
```python
# prompt updated to request cleaning_suggestions...
# but parser not updated
def parse_llm_response(raw: str) -> LLMResponse:
    parsed = json.loads(strip_code_fences(raw))
    return LLMResponse(
        code=parsed["code"],
        explanation=parsed["explanation"],
        # cleaning_suggestions not extracted — silently dropped
    )
```

#### ✓ Pattern: Update prompt and parser atomically
```python
def parse_llm_response(raw: str) -> LLMResponse:
    parsed = json.loads(strip_code_fences(raw))
    return LLMResponse(
        code=parsed["code"],
        explanation=parsed["explanation"],
        cleaning_suggestions=parsed.get("cleaning_suggestions"),  # New field with safe default
    )
```

**Why this matters:** Prompt and parser are tightly coupled — they cannot be deployed or tested separately. Treat them as atomic: when updating the expected response schema in the prompt, also update the parser to handle the new field (using `.get()` for backward compatibility).

---

### LLM Output Invariant Validation

The LLM generates arbitrary Python code for `executor.py` to run. Even with a strong system prompt specifying available variables, the model may violate sandbox assumptions. Common violations include:

- **Referencing undefined variables:** Using a library or variable not pre-loaded in the exec namespace (e.g., `import requests` when network imports are restricted)
- **Reassigning `df` without signaling:** Mutating the dataframe without the `dataframe_changed` flag being set
- **Schema violations:** Missing `code` or `explanation` fields in the JSON response

#### ✓ Pattern: Validate at the parse boundary
```python
def parse_llm_response(raw: str) -> LLMResponse:
    parsed = json.loads(strip_code_fences(raw))
    
    # Validate required fields before entering the pipeline
    if "code" not in parsed:
        raise ValueError("LLM response missing required 'code' field")
    if "explanation" not in parsed:
        raise ValueError("LLM response missing required 'explanation' field")
    
    return LLMResponse(**parsed)
```

#### ✓ Pattern: Test with realistic (messy) LLM outputs
```python
# Include edge cases in test fixtures — not just well-formed responses
mock_llm.return_value = {
    "code": "import requests\nrequests.get('http://example.com')",  # Restricted import
    "explanation": "Fetches external data"
}
# executor.py should catch this at runtime; parser should not silently accept it
```

**Why this matters:** Mocked tests with perfectly-formed LLM outputs don't catch real-world edge cases. The LLM doesn't inherently understand the sandbox's restrictions. Always include malformed or boundary-violating LLM outputs in integration tests for `executor.py`.

---

### LLM vs. Deterministic Code Responsibility Split

`executor.py` runs LLM-generated code. The LLM decides *what analysis* to perform; deterministic code handles *how* it's sandboxed and how results are captured.

#### ✓ Pattern: Deterministic executor, LLM decides content
```python
# The LLM emits analysis code. executor.py deterministically handles the rest.

def run_code(code: str, namespace: dict) -> ExecutionResult:
    """Run LLM-generated code. Deterministically capture figures and output."""
    stdout_buffer = io.StringIO()
    
    with contextlib.redirect_stdout(stdout_buffer):
        exec(code, namespace)  # LLM decides what runs; we decide how
    
    figures = _capture_figures()  # Deterministic figure capture
    return ExecutionResult(
        stdout=stdout_buffer.getvalue(),
        figures=figures,
        dataframe_changed=_check_df_changed(namespace),
    )
```

#### ❌ Anti-Pattern: Letting the LLM influence execution mechanics
```python
# BAD: Don't let the LLM emit code that modifies plt capture hooks,
# imports new libraries, or changes how results are returned.
# The system prompt should make this boundary explicit.
```

**Why this matters:** Giving the LLM full control over execution introduces hallucination risk for structural decisions (e.g., it may try to `import requests` or modify `__builtins__`). The clean contract is: LLM produces analysis logic, `executor.py` enforces the sandbox invariants.

---

### LLM Option Text to Deterministic Action Mapping

When the LLM produces user-facing option text (e.g., cleaning suggestion buttons like "Drop rows" or "Fill with median"), the frontend must translate that free-form text into a deterministic backend action name. Use a normalized lookup table on the frontend rather than passing LLM text directly to the backend.

#### ✓ Pattern: Explicit lookup table with normalization
```typescript
// Frontend: normalize LLM option text to backend action names
const OPTION_TO_ACTION: Record<string, string> = {
  "drop rows": "drop_missing_rows",
  "drop missing rows": "drop_missing_rows",
  "fill with median": "fill_median",
  "drop duplicates": "drop_duplicates",
  "remove duplicates": "drop_duplicates",
};

function resolveAction(optionText: string): string | null {
  const normalized = optionText.toLowerCase().trim();
  return OPTION_TO_ACTION[normalized] ?? null;
}
```

#### ❌ Anti-Pattern: Passing LLM text directly to the backend
```typescript
// BAD: backend receives free-form text like "Drop the duplicate rows please"
await fetch("/api/clean", {
  body: JSON.stringify({ action: option }),  // LLM text as action — fragile
});
```

**Why this matters:** The LLM may use synonyms, different casing, or slightly different phrasing each time. A normalization layer with multiple aliases per action absorbs this variance. The backend only needs to validate against a small set of known action strings (`VALID_ACTIONS`). Include common synonyms in the lookup table (e.g., both "drop duplicates" and "remove duplicates"). When a new action is added, update both the backend's `VALID_ACTIONS` and the frontend's `OPTION_TO_ACTION`.

---

### Multi-Stage Prompt Chains with a Generic Parser

When building a multi-stage LLM workflow where each stage returns different fields (e.g., stage 1 returns `target_column`, stage 2 returns `features`), prefer a single generic parser that passes through all fields rather than per-stage parsers.

#### ✓ Pattern: Generic pass-through parser
```python
def parse_ml_step_response(raw: str) -> dict:
    """Pass through all fields; each stage handler extracts what it needs."""
    cleaned = strip_code_fences(raw)
    parsed = json.loads(cleaned)
    if "explanation" not in parsed:
        parsed["explanation"] = ""  # safe default for the one universal field
    return parsed
```

#### ❌ Anti-Pattern: Per-stage parsers
```python
# BAD: N parsers for N stages, each tightly coupled to the stage schema.
# Adding a field to one stage requires finding the right parser to update.
def parse_target_response(raw): ...
def parse_feature_response(raw): ...
def parse_model_response(raw): ...
```

**Why this matters:** Stage-specific parsers create tight coupling between the parser layer and the prompt schema. The generic parser delegates field extraction to the handler that knows the current stage — keeping the parse boundary thin and the stage-specific logic co-located with the state update.

---

### Prefer Deterministic Heuristics Over LLM Calls for Classifiable Inputs

When the decision can be made reliably from data properties (e.g., dtype, unique value count, shape), use a pure heuristic function instead of an LLM call. Reserve LLM calls for tasks requiring judgment, natural language understanding, or domain reasoning.

#### ✓ Pattern: Pure heuristic for problem type inference
```python
CLASSIFICATION_UNIQUE_VALUE_THRESHOLD = 10

def infer_problem_type(df, target_column: str) -> str:
    """Deterministic, fast, testable — no LLM call needed."""
    col = df[target_column]
    if col.dtype == "object" or col.dtype == "bool":
        return "classification"
    if col.nunique() <= CLASSIFICATION_UNIQUE_VALUE_THRESHOLD:
        return "classification"
    return "regression"
```

#### ❌ Anti-Pattern: LLM call for a deterministic decision
```python
# BAD: slow, non-deterministic, costs tokens, and the LLM might get it wrong
prompt = f"Is column '{target}' with dtype {dtype} a classification or regression target?"
result = call_llm(prompt, ...)
```

**Why this matters:** LLM calls add latency, cost, and non-determinism. For decisions that can be made from structured data properties with clear rules, a pure function is faster, cheaper, always testable, and never hallucinates.

---

### Model Version Management

When hardcoding LLM model identifiers in `llm.py`:

- **Document the model constant location** — Note in `architecture.md` where the model name is defined so it's easy to find and update
- **Expect model deprecation** — Model names become obsolete; plan for periodic updates
- **Check API responses for 404** — A `not_found_error` with the model name indicates the model was deprecated

#### Troubleshooting model errors

If you see an error like:
```
Error code: 404 - {'type': 'error', 'error': {'type': 'not_found_error', 'message': 'model: claude-3-5-sonnet-20241022'}}
```

This means the model name is outdated. Check Anthropic's current model list and update the model constant in `backend/llm.py`.

---

## FastAPI

### Error Responses

When an endpoint returns validation errors (e.g., missing required fields, invalid file format, unknown session ID), return **400 status** with a structured response body rather than 200 with `success: false`. Use `JSONResponse` when you need both a non-200 status and a custom body shape.

#### When to use each

| Situation | Use | Example |
|-----------|-----|---------|
| Auth failure, not found, invalid input | `HTTPException` | `raise HTTPException(status_code=404, detail="Session not found")` |
| Validation error with custom body | `JSONResponse` | `return JSONResponse(status_code=400, content={"success": False, "error": "..."})` |
| Success with Pydantic model | `response_model` | `@router.post("/upload", response_model=UploadResponse)` |

#### ❌ Anti-Pattern: 200 OK for validation failure
```python
# BAD: Client cannot distinguish validation failure from success
@app.post("/api/upload")
async def upload(file: UploadFile):
    if not file.filename.endswith((".csv", ".xlsx")):
        return {"success": False, "error": "Unsupported file type"}
    # Returns 200 — client must check body to know it failed
```

#### ✓ Pattern: JSONResponse for validation errors
```python
# GOOD: HTTP status reflects outcome
@app.post("/api/upload")
async def upload(file: UploadFile):
    if not file.filename.endswith((".csv", ".xlsx")):
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Unsupported file type. Upload a .csv or .xlsx file."}
        )
```

**Why this matters:** The frontend SSE client and any retry logic checks `response.status_code` first. Returning 200 for failures forces every caller to inspect the body, and breaks middleware that treats 4xx as client errors.

---

## Frontend / SSE from POST Endpoints

### EventSource Only Supports GET — Use fetch + ReadableStream for POST

The browser's `EventSource` API only works with GET requests. If the backend SSE endpoint requires POST (e.g., sending a JSON body with session ID and question), `EventSource` will fail silently or throw. Use `fetch()` with `response.body.getReader()` and manually parse the SSE `event:` / `data:` lines.

#### ❌ Anti-Pattern: EventSource with a POST endpoint
```typescript
// BAD: EventSource only sends GET — the request body is ignored,
// and the backend returns 405 Method Not Allowed
const source = new EventSource("/api/chat");
source.onmessage = (e) => console.log(e.data);
```

#### ✓ Pattern: fetch + ReadableStream for POST-based SSE
```typescript
const response = await fetch("/api/chat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ session_id: sessionId, question }),
});

const reader = response.body!.getReader();
const decoder = new TextDecoder();
let buffer = "";

for (;;) {
  const { done, value } = await reader.read();
  if (done) break;

  buffer += decoder.decode(value, { stream: true });
  const parts = buffer.split("\n\n");
  buffer = parts.pop()!; // keep incomplete event in buffer

  for (const part of parts) {
    // parse "event: <type>\ndata: <payload>" from each part
  }
}
```

**Why this matters:** This surfaced during Step 9 (Q&A frontend). The backend's `/api/chat` endpoint is POST because it accepts a JSON body. Attempting to use `EventSource` wastes a debugging cycle before discovering the GET-only limitation. The `fetch` + `ReadableStream` pattern is well-established and gives full control over request method, headers, and body.

---

## Python / Subprocess Execution

### Use Processes, Not Threads, for Untrusted Code

When executing LLM-generated or user-provided code that may hang (infinite loops, blocking I/O), always run it in a separate **process** — never a thread.

A thread shares the GIL and Python provides no mechanism to kill it. An infinite loop in a thread burns CPU forever and blocks process exit (including pytest teardown). A process can be killed instantly with `process.kill()`.

#### ❌ Anti-Pattern: Thread-based execution with timeout
```python
# BAD: if the code hangs, the daemon thread keeps running and blocks pytest exit
thread = threading.Thread(target=run_code, daemon=True)
thread.start()
finished.wait(timeout=30)
if not finished.is_set():
    return {"error": "timed out"}  # Thread is still running, can't kill it
```

#### ✓ Pattern: Process-based execution with kill
```python
# GOOD: child process is killed cleanly on timeout
process = multiprocessing.Process(target=worker, args=(code, df_pickle, conn), daemon=True)
process.start()
process.join(timeout=30)
if process.is_alive():
    process.kill()   # OS terminates the child immediately
    process.join()
    return {"error": "Code execution timed out"}
```

**Why this matters:** This surfaced during executor.py development — `ThreadPoolExecutor` and daemon threads both left zombie threads running `while True: pass` that blocked pytest for 60+ seconds. Switching to `multiprocessing.Process` with `process.kill()` gave clean 3-second test runs.

---

### Prefer multiprocessing.Process Over ProcessPoolExecutor for Single-Shot Execution

`ProcessPoolExecutor` requires OS semaphores (`os.sysconf("SC_SEM_NSEMS_MAX")`) that sandboxed or restricted environments may block. Raw `multiprocessing.Process` + `Pipe` doesn't need semaphores and gives you direct control over the child lifecycle.

#### ❌ Anti-Pattern: ProcessPoolExecutor for one-off execution
```python
# BAD: requires semaphores; fails in sandboxed environments
with ProcessPoolExecutor(max_workers=1) as pool:
    future = pool.submit(worker, code, df_pickle)
    result = future.result(timeout=30)
```

#### ✓ Pattern: Direct Process + Pipe
```python
# GOOD: no semaphore dependency; works in all environments
parent_conn, child_conn = multiprocessing.Pipe(duplex=False)
proc = multiprocessing.Process(target=worker, args=(code, df_pickle, child_conn))
proc.start()
child_conn.close()
proc.join(timeout=30)
if proc.is_alive():
    proc.kill()
    proc.join()
```

**Why this matters:** `ProcessPoolExecutor` failed with `PermissionError` on `os.sysconf` inside Cursor's sandbox. The pool abstraction is designed for reusable worker pools, not single-shot subprocess execution.

---

## Python / Testing

### Match Test Assertions to Exact Error Wording

When a test checks an error message string, use the exact wording from the implementation — or better, use a shared constant for the message so the test and implementation can't drift.

#### ❌ Anti-Pattern: Approximate string matching
```python
# In executor.py:
public_result["error"] = "Code execution timed out"

# In test — "timeout" (one word) is NOT in "timed out" (two words)
assert "timeout" in result["error"].lower()  # FAILS
```

#### ✓ Pattern: Exact wording or shared constant
```python
# GOOD: match the exact wording
assert "timed out" in result["error"].lower()

# BETTER: shared constant
TIMEOUT_ERROR_MESSAGE = "Code execution timed out"
# used in both executor.py and test_executor.py
```

**Why this matters:** A near-miss in wording wastes a full debugging cycle. The developer assumes the timeout mechanism is broken when actually the test assertion is just checking for the wrong substring.

---

## Python / asyncio

### asyncio.run() Requires a Coroutine

When calling `asyncio.run()` from synchronous code (e.g., a CLI entry point or test helper), the argument must be a **coroutine** (the return value of calling an `async def` function), not just any awaitable.

#### ❌ Anti-Pattern: Passing a Future to asyncio.run()
```python
# BAD: asyncio.gather() returns a Future, not a coroutine
results = asyncio.run(
    asyncio.gather(*[analyze_chunk(x) for x in chunks])
)
# ValueError: a coroutine was expected, got <_GatheringFuture pending>
```

#### ✓ Pattern: Wrap in an async function
```python
# GOOD: Wrap gather in an async def to produce a coroutine
async def run_all():
    return await asyncio.gather(*[analyze_chunk(x) for x in chunks])

results = asyncio.run(run_all())
```

**Why this matters:** `asyncio.gather()` and similar utilities return Futures that must be `await`ed inside an async context. This error often surfaces only in tests rather than during direct execution.

---

### Environment Variable Loading in CLI Entry Points

When the backend depends on environment variables (e.g., `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`), explicitly load `.env` files at startup using `python-dotenv`:

```python
# main.py or any CLI entry point
def main():
    from dotenv import load_dotenv
    load_dotenv()  # Load .env before accessing env vars
    
    # Now os.environ.get("ANTHROPIC_API_KEY") will find keys from .env
```

**Why this matters:** Tests often mock external dependencies, so missing `.env` loading won't surface until manual testing. Always load `.env` in the FastAPI startup or CLI entry point before any code that reads API keys.

---

## Git Worktrees

This project uses `git worktree` to allow parallel work on different branches from separate directories. Worktrees share a single `.git` database but have independent working trees. Untracked directories (`venv/`, `node_modules/`, `__pycache__/`) are **not** shared — each worktree needs its own.

### Each Worktree Gets Its Own Virtual Environment

Create a local venv in the worktree rather than pointing back to the original project's venv. Sharing a venv across worktrees causes dependency leakage between branches and forces a path-discovery scavenger hunt at the start of every session.

#### Setting up a new worktree for backend work

```bash
cd /path/to/worktree/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

After this, `source backend/venv/bin/activate` works from the worktree root — no special paths needed.

#### ❌ Anti-Pattern: Sharing the original project's venv
```bash
# BAD: fragile path, dependency changes leak across branches,
# every new session starts with "where is the venv?"
ORIGINAL_ROOT=$(git worktree list | head -1 | awk '{print $1}')
source "$ORIGINAL_ROOT/backend/venv/bin/activate"
```

#### ✓ Pattern: Local venv per worktree
```bash
# GOOD: self-contained, discoverable, isolated
source backend/venv/bin/activate
```

**Why this matters:** If branch A adds `anthropic>=0.25` and branch B hasn't updated `requirements.txt` yet, a shared venv silently makes the package available on branch B — hiding a missing dependency that will break in CI or for other developers. A local venv per worktree catches this immediately.

---

### Node Modules Are Also Not Shared

`node_modules/` is untracked and won't exist in a new worktree. Run `npm install` in the worktree's `frontend/` directory before any frontend work.

```bash
cd /path/to/worktree/frontend && npm install
```

---

### File Paths: Always Use the Worktree Path

Code runs from the worktree directory, not the original. All file paths in shell commands, test configurations, and imports must reference the worktree.

#### ❌ Anti-Pattern: Running commands from the original project
```bash
# BAD: tests the wrong checkout
cd /original/backend && pytest
```

#### ✓ Pattern: All work happens in the worktree
```bash
# GOOD: venv and code are both in the worktree
cd /worktree/backend
source venv/bin/activate
pytest tests/ -v
```

---

## Vitest / Frontend Testing

### `clearAllMocks()` Does Not Flush `mockImplementationOnce` Queues — Use `mockReset()`

`vi.clearAllMocks()` resets call counts and recorded arguments, but leaves any queued `mockImplementationOnce` entries intact. If an earlier test queues more one-time implementations than it consumes (e.g., because it queued 5 but only 1 was called), the leftover entries bleed into subsequent tests and are consumed there — silently changing behavior.

#### ❌ Anti-Pattern: `clearAllMocks()` in `beforeEach` when using `mockImplementationOnce`

```typescript
beforeEach(() => {
  vi.clearAllMocks(); // Clears call history but NOT the implementation queue
});

test("feature A", () => {
  vi.mocked(sendMlStep).mockImplementationOnce(hangingPromise); // queued but never consumed
  // ...test only partially exercises the mock...
});

test("feature B", () => {
  vi.mocked(sendMlStep).mockImplementationOnce(successImpl); // consumed as 2nd call
  // But sendMlStep's FIRST call gets the leftover hangingPromise from feature A
  // → test silently hangs or behaves wrong
});
```

#### ✓ Pattern: `mockReset()` per test when using `mockImplementationOnce`

```typescript
beforeEach(() => {
  vi.mocked(sendMlStep).mockReset(); // Clears both call history AND the implementation queue
});
```

Place the `mockReset()` call in a top-level `beforeEach` (outside all `describe` blocks) so it applies to every test regardless of grouping.

**Why this matters:** This is a non-obvious Vitest quirk that produces flaky, order-dependent test failures. The error manifests as a test that passes in isolation but fails when the full suite runs. The real culprit is always a test earlier in the file that queued but didn't consume all its one-time mocks.

---

### Async Error Guard in SSE Callbacks: Use Closure Variables, Not React State

When SSE streams an error and then a done event in sequence (within the same async call), you cannot use React state (`useState`) to prevent the `onDone` handler from advancing the phase. State setters are asynchronous — the updated value won't be visible to the `onDone` closure that runs in the same microtask.

#### ❌ Anti-Pattern: Relying on React state to guard `onDone`

```typescript
const [hadError, setHadError] = useState(false);

sendMlStep(sessionId, stage, input, {
  onError: (msg) => {
    setHadError(true);       // schedules a re-render, does NOT update hadError NOW
    setStageError(msg);
    setIsStageStreaming(false);
  },
  onDone: () => {
    if (hadError) return;    // WRONG: hadError is still false — stale closure
    setPhase("features");    // Phase advances even after an error
  },
});
```

#### ✓ Pattern: Closure variable initialized before the call

```typescript
let hadError = false;  // plain JS variable — readable synchronously within the closure

sendMlStep(sessionId, stage, input, {
  onError: (msg) => {
    hadError = true;          // immediately visible to any code in this closure
    setStageError(msg);
    setIsStageStreaming(false);
  },
  onDone: () => {
    if (hadError) return;     // CORRECT: reads the updated value
    setPhase("features");
  },
});
```

The same pattern applies inside `useEffect` async sequences where multiple `await sendMlStep(...)` calls share a single `hadError` guard.

**Why this matters:** This class of bug causes a phase transition to fire even when the user has seen an error message, leaving the UI in an inconsistent state. It's hard to catch in tests unless the mock explicitly calls `onError` followed by `onDone` in sequence (which real SSE streams do).

---

### Distinct Text for Card Titles vs Body Text Prevents `getByText` Ambiguity

When a component has a card title and body text that share the same substring, `screen.getByText(/substring/i)` throws "Found multiple elements with text matching..." and the test fails. This is especially common in wizard-style UIs where a card heading ("Training Model") echoes the loading message ("Training model...").

#### ❌ Anti-Pattern: Title and body sharing a substring

```tsx
// Card title: "Training Model"
// Body text:  "Training model..."
// Both match /training model/i → getByText throws
screen.getByText(/training model/i); // Fails: multiple matches
```

#### ✓ Pattern: Ensure titles and status messages are textually distinct

```tsx
// Card title: "Running Training"   ← distinct from body
// Body text:  "Training model..."
screen.getByText(/running training/i); // Unique match
```

The same collision can occur between completed-phase summary labels and results explanation text (e.g., "Training complete" appearing in both the collapsed summary and the LLM explanation returned by the mock). Use distinct phrasing for summary labels: prefer `"Training: finished"` over `"Training complete"`.

**Why this matters:** These collisions are invisible until tests run — the component renders correctly, but test queries fail with cryptic errors. Establishing distinct naming conventions for card titles, status messages, and completed-phase summaries prevents a debugging cycle that looks like a state bug but is actually a text uniqueness problem.
