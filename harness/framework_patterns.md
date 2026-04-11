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
