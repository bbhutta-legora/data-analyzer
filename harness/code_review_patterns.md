# Code Review Patterns

Use this document to review code after it has been written. Each section contains patterns (good) and anti-patterns (bad) with concrete examples. When reviewing, flag violations with the section name and a one-sentence explanation of the problem.

This document complements `coding_principles.md` (authoring-time guidance) and `framework_patterns.md` (technology-specific gotchas). Those documents tell you how to write code. This document tells you how to evaluate code that's already written.

---

## How to Use This Document (for AI agents)

When reviewing code, scan each changed file against the sections below. For each violation found, report:

```
[Section Name] filename:line — one-sentence description of the problem
Suggested fix: concrete change to make
```

Not every section applies to every file. Use judgment — a one-line constant definition doesn't need early returns. Prioritize flagging issues that would cause bugs or confusion over stylistic preferences.

---

## 1. Function Size and Responsibility

A function should do one thing and be understandable without scrolling. If a function requires more than ~4 facts held in working memory simultaneously, it's too complex.

### ❌ Anti-Pattern: Multi-responsibility function

```python
def process_upload(file: UploadFile, session_id: str) -> dict:
    if not file.filename.endswith((".csv", ".xlsx")):
        return {"error": "bad type"}
    
    content = file.read()
    if file.filename.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(content))
    else:
        df = pd.read_excel(io.BytesIO(content))
    
    df = df.drop_duplicates()
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    
    for col in df.select_dtypes(include="object"):
        try:
            df[col] = pd.to_numeric(df[col])
        except ValueError:
            pass
    
    missing = df.isnull().sum()
    stats = df.describe()
    # ... 40 more lines of analysis ...
    
    sessions[session_id] = df
    return {"rows": len(df), "cols": len(df.columns), "missing": missing.to_dict()}
```

### ✓ Pattern: Composed single-responsibility functions

```python
def process_upload(file: UploadFile, session_id: str) -> dict:
    validate_file_extension(file.filename)
    df = read_dataframe(file)
    df = normalize_columns(df)
    summary = generate_upload_summary(df)
    sessions[session_id] = df
    return summary
```

**Review signal:** If you need to read past the first screen of a function to understand what it does, flag it. If the function name doesn't accurately describe everything it does, it's doing too much.

---

## 2. Early Returns and Guard Clauses

Nested conditionals force the reader to track preconditions through indentation. Early returns let the reader forget about handled cases and focus on the happy path.

### ❌ Anti-Pattern: Deep nesting

```python
def get_column_stats(df: pd.DataFrame, column: str) -> dict:
    if df is not None:
        if column in df.columns:
            if df[column].dtype in ("int64", "float64"):
                return {"mean": df[column].mean(), "std": df[column].std()}
            else:
                return {"unique": df[column].nunique()}
        else:
            raise ValueError(f"Column {column} not found")
    else:
        raise ValueError("DataFrame is None")
```

### ✓ Pattern: Guard clauses with early returns

```python
def get_column_stats(df: pd.DataFrame, column: str) -> dict:
    if df is None:
        raise ValueError("DataFrame is None")
    if column not in df.columns:
        raise ValueError(f"Column {column} not found")
    
    if df[column].dtype in ("int64", "float64"):
        return {"mean": df[column].mean(), "std": df[column].std()}
    return {"unique": df[column].nunique()}
```

**Review signal:** More than 2 levels of nesting is a flag. Check whether the inner logic can be flattened with early returns.

---

## 3. Naming

Names should be greppable, unambiguous, and reveal intent. A good name eliminates the need for a comment.

### ❌ Anti-Pattern: Generic or abbreviated names

```python
def proc(d, q, k):
    r = call_api(d, q, k)
    if r.ok:
        return r.data
    return None

temp = get_data()
result = process(temp)
items = fetch()
```

### ✓ Pattern: Intent-revealing names

```python
def execute_analysis_query(dataset_metadata: str, user_question: str, api_key: str) -> AnalysisResult | None:
    llm_response = call_analysis_api(dataset_metadata, user_question, api_key)
    if llm_response.ok:
        return llm_response.data
    return None

column_statistics = compute_column_statistics(uploaded_dataframe)
cleaning_suggestions = generate_cleaning_suggestions(column_statistics)
```

### ❌ Anti-Pattern: Boolean names that don't read as questions

```python
process = True
data = False
status = check_upload()
```

### ✓ Pattern: Boolean names that read as yes/no questions

```python
should_process = True
is_data_loaded = False
is_valid_upload = check_upload()
```

**Review signals:**
- Single-letter variables outside of list comprehensions or trivial loops
- Names like `data`, `result`, `temp`, `info`, `item`, `val`, `obj` — too generic to grep
- Abbreviations that aren't universally understood (`df` is fine for DataFrames in a data science codebase; `cfg` for config is borderline; `proc` for process is not)

---

## 4. Error Handling

Errors should be handled at the right level. Catching too broadly hides bugs. Not catching at all crashes the user. Silently swallowing errors is always wrong.

### ❌ Anti-Pattern: Bare except or overly broad catch

```python
try:
    result = execute_generated_code(code, namespace)
    return {"output": result.stdout, "figures": result.figures}
except Exception:
    return {"output": "", "figures": []}
```

### ✓ Pattern: Catch specific exceptions, preserve context

```python
try:
    result = execute_generated_code(code, namespace)
    return {"output": result.stdout, "figures": result.figures}
except SyntaxError as e:
    logger.warning("LLM generated invalid Python syntax", extra={"code": code, "error": str(e)})
    return {"error": f"Code syntax error: {e}", "retryable": True}
except NameError as e:
    logger.warning("LLM referenced undefined variable", extra={"code": code, "error": str(e)})
    return {"error": f"Undefined variable: {e}", "retryable": True}
except ExecutionTimeoutError:
    return {"error": "Code execution timed out. Try a simpler analysis.", "retryable": False}
```

### ❌ Anti-Pattern: Swallowing errors silently

```python
def load_session(session_id: str) -> pd.DataFrame | None:
    try:
        return sessions[session_id]
    except KeyError:
        pass  # silently returns None
```

### ✓ Pattern: Log or propagate, never swallow

```python
def load_session(session_id: str) -> pd.DataFrame:
    if session_id not in sessions:
        raise SessionNotFoundError(f"Session {session_id} does not exist or has expired")
    return sessions[session_id]
```

**Review signals:**
- `except Exception` or bare `except:` without re-raising — almost always a bug hider
- `except` blocks that only contain `pass`
- Error messages that don't include enough context to debug (what input caused the error?)
- Catching exceptions around code that shouldn't fail (e.g., dictionary access with a key you just validated)

---

## 5. Return Type Consistency

A function should return the same shape in all code paths. Mixed return types force every caller to handle multiple shapes.

### ❌ Anti-Pattern: Mixed return types

```python
def analyze_column(df: pd.DataFrame, column: str):
    if column not in df.columns:
        return "Column not found"  # str
    if df[column].isnull().all():
        return None  # NoneType
    return {"mean": df[column].mean(), "std": df[column].std()}  # dict
```

### ✓ Pattern: Consistent return type

```python
@dataclass
class ColumnAnalysis:
    success: bool
    error: str | None = None
    mean: float | None = None
    std: float | None = None

def analyze_column(df: pd.DataFrame, column: str) -> ColumnAnalysis:
    if column not in df.columns:
        return ColumnAnalysis(success=False, error=f"Column '{column}' not found")
    if df[column].isnull().all():
        return ColumnAnalysis(success=False, error=f"Column '{column}' is entirely null")
    return ColumnAnalysis(success=True, mean=df[column].mean(), std=df[column].std())
```

### ✓ Also acceptable: Raise on invalid input, return on success

```python
def analyze_column(df: pd.DataFrame, column: str) -> dict:
    if column not in df.columns:
        raise ValueError(f"Column '{column}' not found")
    if df[column].isnull().all():
        raise ValueError(f"Column '{column}' is entirely null")
    return {"mean": df[column].mean(), "std": df[column].std()}
```

**Review signal:** Check all return statements in a function. If they return different types (str vs dict vs None), flag it. The caller shouldn't need to `isinstance()` check the return value.

---

## 6. Magic Values

Unexplained literals scattered through code make it impossible to understand intent or safely change thresholds.

### ❌ Anti-Pattern: Literals in logic

```python
if len(df) > 10000:
    df = df.sample(10000)

if missing_pct > 0.4:
    suggestion = "drop"

time.sleep(2)
```

### ✓ Pattern: Named constants with domain meaning

```python
MAX_ROWS_FOR_VISUALIZATION = 10_000
MISSING_VALUE_DROP_THRESHOLD = 0.4
LLM_RETRY_DELAY_SECONDS = 2

if len(df) > MAX_ROWS_FOR_VISUALIZATION:
    df = df.sample(MAX_ROWS_FOR_VISUALIZATION)

if missing_pct > MISSING_VALUE_DROP_THRESHOLD:
    suggestion = "drop"

time.sleep(LLM_RETRY_DELAY_SECONDS)
```

**Review signal:** Any numeric literal other than 0, 1, or -1 in business logic. Any string literal used for comparison or branching (e.g., `if status == "ready"`). These should be constants with names that explain the domain reason for the value.

---

## 7. Comments

Comments should explain *why*, not *what*. The code already says what it does. A comment that restates the code is noise that will go stale.

### ❌ Anti-Pattern: Narration comments

```python
# Import pandas
import pandas as pd

# Read the CSV file
df = pd.read_csv(path)

# Get the number of rows
row_count = len(df)

# Check if the dataframe is empty
if df.empty:
    # Return an error
    return {"error": "Empty dataset"}
```

### ✓ Pattern: Comments that explain non-obvious decisions

```python
import pandas as pd

df = pd.read_csv(path)
row_count = len(df)

# Empty datasets cause division-by-zero in the correlation matrix calculation
# downstream — catch it here with a clear message rather than letting it
# surface as a cryptic numpy error.
if df.empty:
    return {"error": "Empty dataset"}
```

### ✓ Pattern: Comments that explain *why not* the obvious approach

```python
# Using iterrows() instead of vectorized ops here because each row's
# cleaning depends on the previous row's cleaned value (running correction).
# Vectorized approaches were 3x faster but produced incorrect results
# for consecutive error rows.
for idx, row in df.iterrows():
    ...
```

**Review signals:**
- Comments that begin with "Get the...", "Set the...", "Check if...", "Return the..." — almost always narration
- Comments that could be replaced by renaming the variable or function they describe
- Commented-out code without explanation (should be deleted, not commented)
- TODO/FIXME without a description of *what* needs to be done

---

## 8. Mutable Default Arguments

Python's most famous gotcha. Mutable defaults are shared across all calls to the function.

### ❌ Anti-Pattern: Mutable default argument

```python
def add_column_stats(column: str, stats_list: list = []) -> list:
    stats_list.append(compute_stats(column))
    return stats_list

# First call: returns [stats_a] ✓
# Second call: returns [stats_a, stats_b] ✗ — previous call's data leaked
```

### ✓ Pattern: None sentinel with internal initialization

```python
def add_column_stats(column: str, stats_list: list | None = None) -> list:
    if stats_list is None:
        stats_list = []
    stats_list.append(compute_stats(column))
    return stats_list
```

**Review signal:** Any function parameter with a default value of `[]`, `{}`, or `set()`. This is always a bug.

---

## 9. Separation of I/O and Logic

Pure logic should be testable without touching the filesystem, network, or database. Functions that mix computation with I/O are hard to test and hard to reuse.

### ❌ Anti-Pattern: Logic interleaved with I/O

```python
def generate_notebook(session_id: str) -> str:
    df = pd.read_csv(f"/tmp/sessions/{session_id}/data.csv")
    
    cells = []
    for msg in load_chat_history(session_id):
        if msg["role"] == "assistant" and "code" in msg:
            cells.append(nbformat.new_code_cell(msg["code"]))
        if msg["role"] == "assistant" and "explanation" in msg:
            cells.append(nbformat.new_markdown_cell(msg["explanation"]))
    
    nb = nbformat.new_notebook(cells=cells)
    path = f"/tmp/sessions/{session_id}/export.ipynb"
    with open(path, "w") as f:
        nbformat.write(nb, f)
    return path
```

### ✓ Pattern: Pure logic function + thin I/O wrapper

```python
def build_notebook_cells(chat_history: list[dict]) -> list:
    """Pure function: chat messages → notebook cells. No I/O."""
    cells = []
    for msg in chat_history:
        if msg["role"] == "assistant" and "code" in msg:
            cells.append(nbformat.new_code_cell(msg["code"]))
        if msg["role"] == "assistant" and "explanation" in msg:
            cells.append(nbformat.new_markdown_cell(msg["explanation"]))
    return cells

def export_notebook(session_id: str) -> str:
    """Thin I/O wrapper that calls the pure function."""
    chat_history = load_chat_history(session_id)
    cells = build_notebook_cells(chat_history)
    nb = nbformat.new_notebook(cells=cells)
    path = f"/tmp/sessions/{session_id}/export.ipynb"
    with open(path, "w") as f:
        nbformat.write(nb, f)
    return path
```

**Review signal:** If a function both reads/writes external state AND contains branching logic or data transformation, it should be split. The test question: "Can I unit test the core logic of this function by passing arguments, without mocking file I/O or network calls?"

---

## 10. String Building for Prompts

Prompt construction gets messy fast. Inconsistent formatting, forgotten context, and string soup make prompts impossible to debug.

### ❌ Anti-Pattern: String concatenation and inline formatting

```python
prompt = "You are a data analyst. "
prompt += "The dataset has columns: " + ", ".join(df.columns) + ". "
prompt += "The user asked: " + question + ". "
if has_cleaning_history:
    prompt += "Previous cleaning steps: " + str(cleaning_steps) + ". "
prompt += "Respond in JSON."
```

### ✓ Pattern: Structured template with clear sections

```python
ANALYSIS_PROMPT_TEMPLATE = """You are a data analyst helping a junior data scientist.

DATASET COLUMNS:
{column_listing}

COLUMN TYPES:
{type_listing}

{cleaning_context}

USER QUESTION:
\"\"\"{user_question}\"\"\"

Respond with valid JSON only. Do not ask clarifying questions."""

def build_analysis_prompt(df: pd.DataFrame, question: str, cleaning_history: list[str] | None = None) -> str:
    cleaning_context = ""
    if cleaning_history:
        steps = "\n".join(f"- {step}" for step in cleaning_history)
        cleaning_context = f"PREVIOUS CLEANING STEPS:\n{steps}"
    
    return ANALYSIS_PROMPT_TEMPLATE.format(
        column_listing=", ".join(df.columns),
        type_listing="\n".join(f"- {col}: {dtype}" for col, dtype in df.dtypes.items()),
        cleaning_context=cleaning_context,
        user_question=question,
    )
```

**Review signals:**
- String concatenation (`+`) or f-strings to build multi-line prompts
- Prompts constructed across multiple functions without a clear "here's the final prompt" step
- User input injected into prompts without delimiters (triple quotes, XML tags, etc.)
- No clear separation between system instructions and user-provided content

---

## 11. Test Quality

Tests should verify behavior, not implementation. A test that breaks when you refactor internals (without changing behavior) is a liability.

### ❌ Anti-Pattern: Testing implementation details

```python
def test_analysis_query():
    with patch("src.llm.client.messages.create") as mock_create:
        mock_create.return_value.content = [Mock(text='{"code": "df.head()"}')]
        
        result = analyze("show first rows", df, api_key)
        
        # Testing HOW it works, not WHAT it produces
        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["model"] == "claude-sonnet-4-20250514"
        assert "df.head()" in mock_create.call_args.kwargs["messages"][0]["content"]
```

### ✓ Pattern: Testing observable behavior

```python
def test_analysis_returns_executable_code():
    with patch("src.llm.client.messages.create") as mock_create:
        mock_create.return_value.content = [Mock(text='{"code": "print(df.shape)", "explanation": "Shows dimensions"}')]
        
        result = analyze("how big is the dataset?", sample_df, api_key)
        
        assert result.code is not None
        assert result.explanation is not None
        # Verify the code actually runs — the important behavior
        exec_result = execute_in_sandbox(result.code, {"df": sample_df})
        assert "rows" in exec_result.stdout or exec_result.stdout.strip() != ""
```

### ❌ Anti-Pattern: Tests without assertions

```python
def test_upload_works():
    result = upload_file("test.csv")
    print(result)  # "Looks good in the console" is not a test
```

### ❌ Anti-Pattern: Tests that test the mock

```python
def test_llm_returns_json():
    mock_response = '{"code": "df.head()"}'
    parsed = json.loads(mock_response)
    assert "code" in parsed  # You just tested json.loads, not your code
```

**Review signals:**
- Tests that assert on mock call arguments (testing how, not what)
- Tests with no assertions or only `print()` statements
- Test names that describe implementation (`test_calls_api_twice`) instead of behavior (`test_retries_on_first_failure`)
- Tests that would break if you refactored the internal structure without changing behavior

---

## 12. Unnecessary Complexity

If a simpler construct exists, use it. Complexity that doesn't serve a purpose is a maintenance burden.

### ❌ Anti-Pattern: Overly clever one-liners

```python
columns_with_nulls = dict(filter(lambda x: x[1] > 0, ((c, df[c].isnull().sum()) for c in df.columns)))
```

### ✓ Pattern: Readable equivalent

```python
columns_with_nulls = {col: null_count for col in df.columns if (null_count := df[col].isnull().sum()) > 0}
```

### ✓ Pattern: Even clearer if the walrus operator isn't familiar

```python
null_counts = df.isnull().sum()
columns_with_nulls = null_counts[null_counts > 0].to_dict()
```

### ❌ Anti-Pattern: Premature abstraction

```python
class DataFrameColumnIterator:
    def __init__(self, df): self.df = df
    def __iter__(self): return iter(self.df.columns)
    def __len__(self): return len(self.df.columns)

for col in DataFrameColumnIterator(df):
    ...
```

### ✓ Pattern: Use the built-in

```python
for col in df.columns:
    ...
```

**Review signals:**
- Classes with only `__init__` and one other method (should probably be a function)
- Abstractions with only one user (premature; see `architectural_principles.md` — wait for 3+ use cases)
- Reimplementing standard library or pandas functionality
- Nested comprehensions more than 2 levels deep

---

## 13. State Mutation

Uncontrolled mutation makes code hard to reason about. Prefer creating new values over modifying existing ones, especially for shared data.

### ❌ Anti-Pattern: Mutating input arguments

```python
def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df.drop_duplicates(inplace=True)       # Mutates caller's df
    df.columns = [c.lower() for c in df.columns]  # Mutates caller's df
    return df
```

### ✓ Pattern: Return new values, leave inputs untouched

```python
def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.drop_duplicates()
    cleaned.columns = [c.lower() for c in cleaned.columns]
    return cleaned
```

**Review signals:**
- `inplace=True` on pandas operations (almost never what you want — it's also being deprecated)
- Functions that modify their arguments and return them
- Global or module-level mutable state (dictionaries, lists) modified inside functions without explicit documentation

---

## 14. Import Hygiene

Imports at the top of the file, grouped logically. Inline imports are acceptable only for breaking circular dependencies or conditional heavy dependencies.

### ❌ Anti-Pattern: Scattered imports

```python
def analyze(question: str) -> dict:
    import json
    from src.llm import call_api
    
    response = call_api(question)
    
    import re
    cleaned = re.sub(r"```json\n?", "", response)
    
    return json.loads(cleaned)
```

### ✓ Pattern: Top-level imports, grouped by source

```python
import json
import re

from src.llm import call_api


def analyze(question: str) -> dict:
    response = call_api(question)
    cleaned = re.sub(r"```json\n?", "", response)
    return json.loads(cleaned)
```

### ✓ Acceptable exception: Heavy optional dependency

```python
def render_chart(df: pd.DataFrame, chart_type: str) -> bytes:
    # matplotlib takes ~500ms to import — only pay this cost when actually rendering
    import matplotlib.pyplot as plt
    ...
```

**Review signal:** Any `import` statement inside a function body that isn't justified by a comment explaining why it can't be top-level.

---

## 15. API Contract Discipline

Endpoint handlers should validate inputs at the boundary, use proper HTTP status codes, and return consistent response shapes.

### ❌ Anti-Pattern: Trusting input, inconsistent responses

```python
@app.post("/api/ask")
async def ask(request: Request):
    body = await request.json()
    session = sessions[body["session_id"]]      # KeyError if missing
    question = body["question"]                   # KeyError if missing
    result = await analyze(question, session.df)
    return {"answer": result}                     # No error shape defined
```

### ✓ Pattern: Validate at boundary, typed request/response

```python
class AskRequest(BaseModel):
    session_id: str
    question: str = Field(min_length=1, max_length=2000)

class AskResponse(BaseModel):
    success: bool
    code: str | None = None
    explanation: str | None = None
    error: str | None = None

@app.post("/api/ask", response_model=AskResponse)
async def ask(request: AskRequest):
    if request.session_id not in sessions:
        return JSONResponse(status_code=404, content={"success": False, "error": "Session not found"})
    
    result = await analyze(request.question, sessions[request.session_id].df)
    return AskResponse(success=True, code=result.code, explanation=result.explanation)
```

**Review signals:**
- `await request.json()` without Pydantic validation
- Dictionary key access on unvalidated input without `.get()` or try/except
- Endpoints that return 200 for error cases (see `framework_patterns.md` for details)
- Response shapes that differ between success and error paths with no shared contract

---

## 16. Logging

Logs should be structured, contextual, and at the right level. They're the primary debugging tool when something goes wrong in production.

### ❌ Anti-Pattern: Print-based debugging left in production code

```python
def execute_code(code: str, namespace: dict):
    print("executing code...")
    print(f"code = {code}")
    result = exec(code, namespace)
    print(f"result = {result}")
    print("done!")
    return result
```

### ❌ Anti-Pattern: Logging without context

```python
logger.error("Something went wrong")
logger.info("Processing complete")
```

### ✓ Pattern: Structured logging with context

```python
logger.info("Executing LLM-generated code", extra={
    "session_id": session_id,
    "code_length": len(code),
    "namespace_keys": list(namespace.keys()),
})

try:
    result = exec(code, namespace)
except Exception as e:
    logger.error("Code execution failed", extra={
        "session_id": session_id,
        "error_type": type(e).__name__,
        "error_message": str(e),
        "code_snippet": code[:200],
    })
    raise
```

**Review signals:**
- `print()` statements that aren't part of deliberate user-facing output
- `logger.error()` or `logger.warning()` without enough context to reproduce the issue
- Logging sensitive data (API keys, full user datasets) — check what's in `extra`
- Missing logging around external calls (LLM API, file I/O) where failures are expected

---

## 17. Async Discipline

Mixing sync and async incorrectly blocks the event loop or creates subtle concurrency bugs.

### ❌ Anti-Pattern: Blocking call inside async function

```python
async def upload_and_analyze(file: UploadFile):
    content = file.file.read()                    # Blocking I/O in async context
    df = pd.read_csv(io.BytesIO(content))         # CPU-bound in async context
    time.sleep(2)                                  # Blocks the event loop
    return generate_summary(df)
```

### ✓ Pattern: Use async I/O or offload to thread pool

```python
async def upload_and_analyze(file: UploadFile):
    content = await file.read()                                # Async I/O
    df = await asyncio.to_thread(pd.read_csv, io.BytesIO(content))  # Offload CPU work
    await asyncio.sleep(2)                                     # Non-blocking wait
    return generate_summary(df)
```

**Review signals:**
- `time.sleep()` inside an `async def` function
- Synchronous file I/O (`open()`, `.read()`) inside async functions
- CPU-intensive operations (pandas, numpy) in async functions without `asyncio.to_thread()`
- `asyncio.run()` called inside an already-running event loop

---

## 18. Hardcoded Paths and Environment Assumptions

Code that assumes a specific filesystem layout or environment breaks in CI, Docker, or on another developer's machine.

### ❌ Anti-Pattern: Hardcoded paths

```python
UPLOAD_DIR = "/tmp/dataset_analyzer/uploads"
LOG_FILE = "/Users/dev/logs/app.log"
CONFIG_PATH = "../../config/settings.json"
```

### ✓ Pattern: Configuration-driven paths

```python
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", tempfile.mkdtemp(prefix="dataset_analyzer_"))
LOG_FILE = os.environ.get("LOG_FILE", os.path.join(tempfile.gettempdir(), "app.log"))
CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.json"
```

**Review signals:**
- Absolute paths that include usernames or machine-specific directories
- Relative paths that depend on the current working directory being a specific location
- `os.path.join()` or Path construction using hardcoded separators (`/` vs `\`)

---

## 19. Duplicated Knowledge

When the same fact is expressed in multiple places, they will inevitably drift apart. One source of truth, referenced everywhere.

### ❌ Anti-Pattern: Same validation in multiple places

```python
# In upload.py
ALLOWED_EXTENSIONS = (".csv", ".xlsx", ".xls")

# In validators.py (different file, same list but already drifted)
ALLOWED_EXTENSIONS = (".csv", ".xlsx")

# In frontend (hardcoded again)
# accept=".csv,.xlsx,.xls"
```

### ✓ Pattern: Single source, imported everywhere

```python
# constants.py
ALLOWED_UPLOAD_EXTENSIONS = (".csv", ".xlsx", ".xls")

# upload.py
from src.constants import ALLOWED_UPLOAD_EXTENSIONS

# validators.py
from src.constants import ALLOWED_UPLOAD_EXTENSIONS
```

**Review signal:** Search for the literal value in the codebase. If the same string, number, or list appears in more than one file, it should be extracted to a shared constant. This is especially important for things like allowed file types, error messages shown to users, and configuration defaults.

---

## 20. Dead Code

Commented-out code, unused imports, unreachable branches, and functions that nothing calls are noise. They confuse future readers (including AI agents) about what the code actually does.

### ❌ Anti-Pattern: Commented-out code and unused imports

```python
import os
import sys  # unused
# import requests  # we used to use this for the old API

def old_analyze(df):  # nothing calls this anymore
    pass

def analyze(df):
    # result = df.describe()  # old approach
    # if USE_NEW_METHOD:  # this is always True now
    return compute_statistics(df)
```

### ✓ Pattern: Remove it. Git remembers.

```python
import os

def analyze(df):
    return compute_statistics(df)
```

**Review signals:**
- Commented-out code blocks without a `TODO:` or `FIXME:` explaining why they're kept
- Imports that aren't used anywhere in the file
- Functions or classes with no callers (verify with a codebase-wide grep before flagging)
- `if True:` or `if False:` blocks
- Feature flags that have been permanently on/off for a long time

---

## Quick Reference Checklist

For fast scanning during review, check each changed file against this list:

| # | Check | What to look for |
|---|-------|-----------------|
| 1 | Function size | Can you understand it without scrolling? |
| 2 | Nesting depth | More than 2 levels of indentation? |
| 3 | Naming | Would a grep for this name find only relevant results? |
| 4 | Error handling | Are exceptions caught specifically? Any bare `except`? |
| 5 | Return consistency | Does every return path produce the same type? |
| 6 | Magic values | Any unexplained numbers or strings in logic? |
| 7 | Comments | Do comments explain *why*, not *what*? |
| 8 | Mutable defaults | Any `[]`, `{}`, or `set()` as default arguments? |
| 9 | I/O separation | Can the core logic be unit tested without mocks? |
| 10 | Prompt construction | Are prompts built from templates with clear sections? |
| 11 | Test quality | Do tests verify behavior, not implementation? |
| 12 | Complexity | Is there a simpler way to write this? |
| 13 | Mutation | Are inputs modified in place? |
| 14 | Imports | All at the top? Grouped logically? |
| 15 | API contracts | Inputs validated? Status codes correct? |
| 16 | Logging | Structured with context? No stray prints? |
| 17 | Async discipline | Any blocking calls in async functions? |
| 18 | Hardcoded paths | Any machine-specific or absolute paths? |
| 19 | Duplication | Same fact expressed in multiple places? |
| 20 | Dead code | Commented-out code, unused imports, unreachable branches? |
