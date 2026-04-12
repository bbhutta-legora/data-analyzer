# Smart Dataset Explainer — Implementation Plan

## Build Strategy

**Hybrid approach:** Build the backend core foundation first (session management, sandboxed execution, file upload, plus frontend scaffolding), then deliver features as vertical slices across frontend and backend.

**LLM testing strategy:** Unit tests mock all LLM calls for fast, deterministic TDD. A separate optional integration test suite hits the real LLM API with loose assertions for regression.

**Default choices:** OpenAI as the initial LLM provider. ~50MB file size upload limit.

**Code review gate:** After any step that produces code, once tests pass, the agent must analyze all changed files against `harness/code_review_patterns.md` before committing. No code enters the codebase without passing this review. See the [Mandatory Code Review](#mandatory-code-review) section below for the full procedure.

---

## Summary

| Step | Name | Phase | Complexity | Depends On | PRD Capability | Status |
|------|------|-------|------------|------------|----------------|--------|
| 1 | Project scaffolding + backend setup | Foundation | Low | — | — | ✅ Done |
| 2 | Session management | Foundation | Medium | 1 | — | ✅ Done |
| 3 | Sandboxed executor | Foundation | High | 1 | — | ✅ Done |
| 4 | File upload endpoint | Foundation | Medium | 2, 3 | #1 Upload | ✅ Done |
| 5 | Frontend scaffolding | Foundation | Low | 1 | — | ✅ Done |
| 6 | BYOK setup | Vertical | Low | 4, 5 | #8 BYOK | ✅ Done |
| 7 | Initial summary | Vertical | Medium | 6 | #2 Initial summary | ✅ Done |
| 8 | Q&A backend | Vertical | High | 7 | #3 Conversational Q&A | ✅ Done |
| 9 | Q&A frontend | Vertical | High | 8, 5 | #3 Conversational Q&A | ✅ Done |
| 10 | Data cleaning | Vertical | Medium | 9 | #4 Data cleaning | ✅ Done |
| 11 | Error recovery | Vertical | Medium | 9 | #6 Error recovery | ✅ Done |
| 12 | Guided ML backend | Vertical | High | 8 | #5 Guided ML | ✅ Done |
| 13 | Guided ML frontend | Vertical | Medium | 12, 9 | #5 Guided ML | |
| 14 | Export | Vertical | Medium | 9 | #7 Export | ✅ Done |
| 15 | Help | Vertical | Low | 5 | #9 Help | ✅ Done |

---

## Mandatory Code Review

Every step that produces code follows this workflow. The code review gate sits between "tests pass" and "commit." No exceptions.

### Workflow

```
1. Write tests          → run them → confirm they fail
2. Write implementation → run tests → confirm they pass
3. Code review          → analyze all changed files against harness/code_review_patterns.md
4. Fix violations       → re-run tests → confirm they still pass
5. Commit
```

### Code Review Procedure

After tests pass, scan every changed file against the 20 checks in `harness/code_review_patterns.md`. For each violation found, report it in this format:

```
[Section Name] filename:line — one-sentence description of the problem
Suggested fix: concrete change to make
```

Then fix all reported violations before committing. After fixes, re-run the test suite to confirm nothing broke.

### What to Check

Use the quick reference checklist from `harness/code_review_patterns.md`:

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

### Scaffolding Exception

Steps that only create configuration or scaffolding (e.g., Step 1, Step 5) still go through the review, but checks like test quality (11) and prompt construction (10) can be skipped when there are no tests or prompts in scope.

---

## Phase 1: Foundation

---

### Step 1 — Project Scaffolding + Backend Setup

**Goal:** Create the monorepo directory structure, Python virtual environment, dependency file, and a bare FastAPI application with a health check endpoint.

**Files to create:**

- `backend/main.py`
- `backend/requirements.txt`
- `backend/.gitignore`
- `.gitignore` (root)

**Step order:** Scaffolding only — no behavioral tests needed. Verification is "the server starts and responds."

**Implementation:**

`requirements.txt` pins core dependencies:

```
fastapi>=0.110
uvicorn>=0.29
pandas>=2.2
numpy>=1.26
matplotlib>=3.8
seaborn>=0.13
scikit-learn>=1.4
openai>=1.14
python-multipart>=0.0.9
openpyxl>=3.1
```

`main.py` defines a minimal FastAPI app:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Smart Dataset Explainer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
async def health():
    return {"status": "ok"}
```

**Verification:**

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload &
curl http://localhost:8000/api/health
```

**Expected output:** `{"status":"ok"}`

---

### Step 2 — Session Management

**Goal:** Build the session module that creates, retrieves, and deletes sessions, each holding a dataframe, conversation history, code history, and exec namespace.

**Files to create/modify:**

- `backend/session.py`
- `backend/tests/__init__.py`
- `backend/tests/test_session.py`

**Tests FIRST:**

```python
"""
Tests for session lifecycle management.

Behaviors tested:
- Creating a session returns a unique session ID
- Retrieving a session by ID returns the stored session
- Retrieving a non-existent session returns None
- Deleting a session removes it from the store
- A session stores a dataframe and exposes it
- A session initializes with empty conversation and code history
- A session's exec namespace contains the dataframe as 'df'
"""
import pandas as pd
import pytest
from session import SessionStore


def test_create_session_returns_unique_id():
    store = SessionStore()
    df = pd.DataFrame({"a": [1, 2, 3]})
    id1 = store.create(df)
    id2 = store.create(df)
    assert id1 != id2
    assert isinstance(id1, str)


def test_get_session_returns_stored_session():
    store = SessionStore()
    df = pd.DataFrame({"a": [1, 2, 3]})
    session_id = store.create(df)
    session = store.get(session_id)
    assert session is not None
    assert session.dataframe.equals(df)


def test_get_nonexistent_session_returns_none():
    store = SessionStore()
    assert store.get("nonexistent-id") is None


def test_delete_session_removes_it():
    store = SessionStore()
    df = pd.DataFrame({"a": [1, 2, 3]})
    session_id = store.create(df)
    store.delete(session_id)
    assert store.get(session_id) is None


def test_session_has_empty_history_on_creation():
    store = SessionStore()
    df = pd.DataFrame({"a": [1, 2, 3]})
    session_id = store.create(df)
    session = store.get(session_id)
    assert session.conversation_history == []
    assert session.code_history == []


def test_session_namespace_contains_dataframe():
    store = SessionStore()
    df = pd.DataFrame({"x": [10, 20]})
    session_id = store.create(df)
    session = store.get(session_id)
    assert "df" in session.exec_namespace
    assert session.exec_namespace["df"].equals(df)


def test_session_stores_original_dataframe_separately():
    store = SessionStore()
    df = pd.DataFrame({"a": [1, 2, 3]})
    session_id = store.create(df)
    session = store.get(session_id)
    session.dataframe.drop(columns=["a"], inplace=True)
    assert "a" in session.dataframe_original.columns
```

Run tests — all should fail (module doesn't exist yet):

```bash
cd backend
source venv/bin/activate
python -m pytest tests/test_session.py -v
```

**Then Implementation:**

```python
# session.py
import uuid
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import sklearn


@dataclass
class Session:
    session_id: str
    dataframe_original: pd.DataFrame
    dataframe: pd.DataFrame
    conversation_history: list = field(default_factory=list)
    code_history: list = field(default_factory=list)
    exec_namespace: dict = field(default_factory=dict)
    api_key: str = ""

    def __post_init__(self):
        self.exec_namespace = {
            "pd": pd,
            "np": np,
            "plt": plt,
            "sns": sns,
            "sklearn": sklearn,
            "df": self.dataframe,
            "print": print,
        }


class SessionStore:
    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def create(self, dataframe: pd.DataFrame, api_key: str = "") -> str:
        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            dataframe_original=dataframe.copy(),
            dataframe=dataframe,
            api_key=api_key,
        )
        self._sessions[session_id] = session
        return session_id

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
```

**Verification:**

```bash
cd backend
source venv/bin/activate
python -m pytest tests/test_session.py -v
```

**Expected output:** All 7 tests passing with PASSED status.

---

### Step 3 — Sandboxed Executor

**Goal:** Build the executor module that runs arbitrary Python code in a restricted namespace, captures stdout, captures matplotlib figures as base64 PNG, enforces a timeout, and blocks dangerous operations.

**Files to create/modify:**

- `backend/executor.py`
- `backend/tests/test_executor.py`

**Tests FIRST:**

```python
"""
Tests for sandboxed code execution.

Behaviors tested:
- Executing simple code returns stdout output
- Executing code that produces a matplotlib figure captures it as base64 PNG
- Executing code that modifies the dataframe is reflected in the namespace
- Executing code with a syntax error returns an error message
- Executing code with a runtime error returns an error message
- Attempting to use __import__ is blocked
- Attempting to use open() is blocked
- Code that exceeds the timeout is killed
- Multiple figures are all captured
"""
import base64
import pandas as pd
import pytest
from executor import execute_code


@pytest.fixture
def sample_namespace():
    import numpy as np
    import matplotlib.pyplot as plt
    import seaborn as sns

    df = pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]})
    return {
        "pd": pd,
        "np": np,
        "plt": plt,
        "sns": sns,
        "df": df,
    }


def test_execute_captures_stdout(sample_namespace):
    result = execute_code("print('hello world')", sample_namespace)
    assert result["error"] is None
    assert "hello world" in result["stdout"]


def test_execute_captures_figure_as_base64(sample_namespace):
    code = """
import matplotlib.pyplot as plt
plt.figure()
plt.plot([1, 2, 3], [4, 5, 6])
plt.title('Test Plot')
"""
    result = execute_code(code, sample_namespace)
    assert result["error"] is None
    assert len(result["figures"]) == 1
    decoded = base64.b64decode(result["figures"][0])
    assert decoded[:4] == b'\x89PNG'


def test_execute_modifies_dataframe(sample_namespace):
    code = "df['z'] = df['x'] + df['y']"
    result = execute_code(code, sample_namespace)
    assert result["error"] is None
    assert "z" in sample_namespace["df"].columns


def test_execute_syntax_error_returns_error(sample_namespace):
    result = execute_code("def foo(", sample_namespace)
    assert result["error"] is not None
    assert "SyntaxError" in result["error"]


def test_execute_runtime_error_returns_error(sample_namespace):
    result = execute_code("1 / 0", sample_namespace)
    assert result["error"] is not None
    assert "ZeroDivisionError" in result["error"]


def test_import_is_blocked(sample_namespace):
    result = execute_code("import os", sample_namespace)
    assert result["error"] is not None


def test_open_is_blocked(sample_namespace):
    result = execute_code("open('/etc/passwd')", sample_namespace)
    assert result["error"] is not None


def test_timeout_kills_long_running_code(sample_namespace):
    code = "while True: pass"
    result = execute_code(code, sample_namespace, timeout=2)
    assert result["error"] is not None
    assert "timeout" in result["error"].lower() or "timed out" in result["error"].lower()


def test_multiple_figures_captured(sample_namespace):
    code = """
import matplotlib.pyplot as plt
plt.figure()
plt.plot([1, 2], [3, 4])
plt.figure()
plt.bar([1, 2], [3, 4])
"""
    result = execute_code(code, sample_namespace)
    assert result["error"] is None
    assert len(result["figures"]) == 2
```

Run tests — all should fail:

```bash
cd backend
source venv/bin/activate
python -m pytest tests/test_executor.py -v
```

**Then Implementation:**

```python
# executor.py
import io
import sys
import signal
import base64
import traceback

import matplotlib.pyplot as plt


# REVIEW: This blocklist approach means any new dangerous builtin added in future Python
# versions would be allowed by default. Evaluate whether an allowlist is safer.
BLOCKED_BUILTINS = {"__import__", "open", "eval", "exec", "compile", "globals", "locals"}

SAFE_BUILTINS = {
    k: v for k, v in __builtins__.__dict__.items()
    if k not in BLOCKED_BUILTINS
} if isinstance(__builtins__, dict) is False else {
    k: v for k, v in __builtins__.items()
    if k not in BLOCKED_BUILTINS
}


class TimeoutError(Exception):
    pass


def _timeout_handler(signum, frame):
    raise TimeoutError("Code execution timed out")


def execute_code(code: str, namespace: dict, timeout: int = 30) -> dict:
    """
    Execute code in a restricted namespace.
    Returns dict with keys: stdout, figures, error, dataframe_changed.
    """
    result = {"stdout": "", "figures": [], "error": None, "dataframe_changed": False}

    plt.close("all")

    restricted_namespace = {**namespace}
    restricted_namespace["__builtins__"] = SAFE_BUILTINS

    stdout_capture = io.StringIO()
    old_stdout = sys.stdout

    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(timeout)

    try:
        sys.stdout = stdout_capture
        exec(code, restricted_namespace)
        result["stdout"] = stdout_capture.getvalue()

        fig_nums = plt.get_fignums()
        for fig_num in fig_nums:
            fig = plt.figure(fig_num)
            buf = io.BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight")
            buf.seek(0)
            result["figures"].append(base64.b64encode(buf.read()).decode("utf-8"))
            plt.close(fig)

        if "df" in restricted_namespace and "df" in namespace:
            if not restricted_namespace["df"].equals(namespace["df"]):
                result["dataframe_changed"] = True
            namespace["df"] = restricted_namespace["df"]

    except TimeoutError:
        result["error"] = "Code execution timed out"
    except Exception:
        result["error"] = traceback.format_exc()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
        sys.stdout = old_stdout

    return result
```

**Verification:**

```bash
cd backend
source venv/bin/activate
python -m pytest tests/test_executor.py -v
```

**Expected output:** All 9 tests passing with PASSED status.

---

### Step 4 — File Upload Endpoint

**Goal:** Add the `/api/upload` endpoint to `main.py` that accepts CSV and Excel files, parses them into a pandas DataFrame (with sheet selection for multi-sheet Excel), creates a session, and returns basic dataset metadata (row count, column count, column names, dtypes, missing values). No LLM calls yet — just structural metadata.

**Files to create/modify:**

- `backend/main.py` (modify)
- `backend/tests/test_upload.py`
- `backend/tests/fixtures/` (test CSV/Excel files)

**Tests FIRST:**

```python
"""
Tests for the file upload endpoint.

Behaviors tested:
- Uploading a valid CSV creates a session and returns dataset metadata
- Uploading a valid single-sheet Excel file works the same as CSV
- Uploading a multi-sheet Excel file without specifying sheet returns sheet names for selection
- Uploading a multi-sheet Excel file with a sheet parameter returns that sheet's metadata
- Uploading an invalid file type returns a 400 error
- Uploading an empty file returns a 400 error
- Dataset metadata includes row count, column count, column names, dtypes, missing value counts
- File size exceeding 50MB returns a 413 error
"""
import io
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from main import app


client = TestClient(app)


@pytest.fixture
def sample_csv():
    df = pd.DataFrame({"name": ["Alice", "Bob", None], "age": [30, 25, 35], "score": [90.5, 85.0, None]})
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    return buf.getvalue().encode()


@pytest.fixture
def sample_excel_single_sheet():
    df = pd.DataFrame({"col1": [1, 2], "col2": [3, 4]})
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="Sheet1")
    buf.seek(0)
    return buf.read()


@pytest.fixture
def sample_excel_multi_sheet():
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame({"a": [1]}).to_excel(writer, sheet_name="Sales", index=False)
        pd.DataFrame({"b": [2]}).to_excel(writer, sheet_name="Revenue", index=False)
    buf.seek(0)
    return buf.read()


def test_upload_csv_returns_metadata(sample_csv):
    response = client.post("/api/upload", files={"file": ("data.csv", sample_csv, "text/csv")})
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["row_count"] == 3
    assert data["column_count"] == 3
    assert "name" in data["columns"]
    assert "missing_values" in data


def test_upload_single_sheet_excel(sample_excel_single_sheet):
    response = client.post(
        "/api/upload",
        files={"file": ("data.xlsx", sample_excel_single_sheet,
               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["row_count"] == 2


def test_upload_multi_sheet_excel_returns_sheet_names(sample_excel_multi_sheet):
    response = client.post(
        "/api/upload",
        files={"file": ("data.xlsx", sample_excel_multi_sheet,
               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    )
    assert response.status_code == 200
    data = response.json()
    assert "sheets" in data
    assert "Sales" in data["sheets"]
    assert "Revenue" in data["sheets"]


def test_upload_multi_sheet_with_selection(sample_excel_multi_sheet):
    response = client.post(
        "/api/upload",
        files={"file": ("data.xlsx", sample_excel_multi_sheet,
               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"sheet": "Revenue"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] is not None
    assert "b" in data["columns"]


def test_upload_invalid_file_type():
    response = client.post(
        "/api/upload",
        files={"file": ("data.txt", b"some text", "text/plain")}
    )
    assert response.status_code == 400


def test_upload_empty_file():
    response = client.post(
        "/api/upload",
        files={"file": ("data.csv", b"", "text/csv")}
    )
    assert response.status_code == 400


def test_metadata_includes_dtypes(sample_csv):
    response = client.post("/api/upload", files={"file": ("data.csv", sample_csv, "text/csv")})
    data = response.json()
    assert "dtypes" in data
    assert isinstance(data["dtypes"], dict)


def test_metadata_includes_missing_values(sample_csv):
    response = client.post("/api/upload", files={"file": ("data.csv", sample_csv, "text/csv")})
    data = response.json()
    assert data["missing_values"]["name"] == 1
    assert data["missing_values"]["score"] == 1
```

Run tests — all should fail:

```bash
cd backend
source venv/bin/activate
python -m pytest tests/test_upload.py -v
```

**Then Implementation:**

Update `main.py` to add the upload route, wire in `SessionStore`, parse files, and return metadata.

The upload handler should:
1. Validate file extension (`.csv`, `.xlsx`, `.xls`)
2. Check file size (reject > 50MB)
3. For Excel files with multiple sheets and no `sheet` parameter, return sheet names
4. Parse into a DataFrame, create a session, return metadata

**Verification:**

```bash
cd backend
source venv/bin/activate
python -m pytest tests/test_upload.py -v
```

**Expected output:** All 8 tests passing with PASSED status.

Additionally, manual verification with curl:

```bash
curl -X POST http://localhost:8000/api/upload \
  -F "file=@test_data.csv"
```

**Expected output:** JSON with `session_id`, `row_count`, `column_count`, `columns`, `dtypes`, `missing_values`.

---

### Step 5 — Frontend Scaffolding

**Goal:** Set up the React frontend with Vite, TypeScript, Zustand, screen routing, and proxy config to the backend. The app should render a shell with three screens (setup, upload, chat) and the Vite dev server should successfully proxy API calls to the FastAPI backend.

**Files to create:**

- `frontend/package.json`
- `frontend/vite.config.ts`
- `frontend/tsconfig.json`
- `frontend/index.html`
- `frontend/src/main.tsx`
- `frontend/src/App.tsx`
- `frontend/src/store.ts`
- `frontend/src/api.ts`
- `frontend/.gitignore`

**Step order:** Scaffolding — no behavioral tests needed. Verification is "the app renders and the proxy works."

**Implementation:**

`vite.config.ts` must include a proxy to forward `/api` requests to the backend:

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000'
    }
  }
})
```

`store.ts` defines the initial Zustand store shape:

```typescript
import { create } from 'zustand'

interface AppState {
  sessionId: string | null
  apiKey: string | null
  messages: any[]
  isStreaming: boolean
  datasetInfo: any | null
  currentScreen: 'setup' | 'upload' | 'chat'
  setApiKey: (key: string) => void
  setScreen: (screen: 'setup' | 'upload' | 'chat') => void
}

export const useStore = create<AppState>((set) => ({
  sessionId: null,
  apiKey: null,
  messages: [],
  isStreaming: false,
  datasetInfo: null,
  currentScreen: 'setup',
  setApiKey: (key) => set({ apiKey: key }),
  setScreen: (screen) => set({ currentScreen: screen }),
}))
```

`App.tsx` renders the current screen based on store state (placeholder divs for now).

**Verification:**

```bash
cd frontend
npm install
npm run dev &
# Wait for Vite to start, then:
curl http://localhost:5173/api/health
```

**Expected output:** `{"status":"ok"}` — confirming the proxy forwards to the backend.

Also verify in a browser: navigate to `http://localhost:5173` and see the shell app render.

---

## Phase 2: Vertical Slices

---

### Step 6 — BYOK Setup

**Goal:** Build the API key input screen where the user enters their OpenAI API key, validate it against the OpenAI API, and transition to the upload screen on success.

**Files to create/modify:**

- `backend/main.py` (add `/api/validate-key` route)
- `backend/tests/test_validate_key.py`
- `frontend/src/components/ApiKeyInput.tsx`
- `frontend/src/store.ts` (modify)
- `frontend/src/api.ts` (modify)

**Tests FIRST (backend):**

```python
"""
Tests for API key validation endpoint.

Behaviors tested:
- A valid API key returns success
- An empty API key returns a 400 error
- An invalid API key returns a 401 error
"""
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_valid_key_returns_success():
    with patch("main.validate_openai_key") as mock_validate:
        mock_validate.return_value = True
        response = client.post("/api/validate-key", json={"api_key": "sk-test-valid-key"})
        assert response.status_code == 200
        assert response.json()["valid"] is True


def test_empty_key_returns_400():
    response = client.post("/api/validate-key", json={"api_key": ""})
    assert response.status_code == 400


def test_invalid_key_returns_401():
    with patch("main.validate_openai_key") as mock_validate:
        mock_validate.return_value = False
        response = client.post("/api/validate-key", json={"api_key": "sk-invalid"})
        assert response.status_code == 401
```

Run tests — all should fail:

```bash
cd backend
source venv/bin/activate
python -m pytest tests/test_validate_key.py -v
```

**Then Implementation:**

Backend: Add a `/api/validate-key` POST route. The validation function makes a lightweight API call (e.g., list models) to check if the key works.

Frontend: Build `ApiKeyInput.tsx` with a text input, submit button, error display, and loading state. On success, store the key in Zustand and transition to the upload screen.

**Verification:**

```bash
cd backend
source venv/bin/activate
python -m pytest tests/test_validate_key.py -v
```

**Expected output:** All 3 tests passing.

Manual verification: Open the app in a browser, enter a valid OpenAI API key, and confirm the screen transitions to upload.

---

### Step 7 — Initial Summary

**Goal:** On file upload, call the LLM to generate an initial summary including data quality issues, cleaning suggestions, and 3–5 suggested questions. Display the summary, suggestions, and clickable question chips in the frontend.

**Files to create/modify:**

- `backend/llm.py` (create)
- `backend/main.py` (modify upload route to call LLM)
- `backend/tests/test_llm.py`
- `frontend/src/components/FileUpload.tsx` (create)
- `frontend/src/components/DataSummary.tsx` (create)
- `frontend/src/store.ts` (modify)
- `frontend/src/api.ts` (modify)

**Tests FIRST (backend):**

```python
"""
Tests for LLM prompt construction and response parsing.

Behaviors tested:
- Prompt includes dataset metadata (columns, dtypes, shape, sample rows)
- Prompt includes the system role definition
- Response parser extracts explanation, cleaning_suggestions, and suggested_questions
- Response parser handles missing optional fields gracefully
- Response parser handles malformed JSON by returning an error
"""
from unittest.mock import patch, AsyncMock
import pandas as pd
import pytest
from llm import build_summary_prompt, parse_summary_response


def test_summary_prompt_includes_column_names():
    df = pd.DataFrame({"revenue": [100], "cost": [50]})
    prompt = build_summary_prompt(df)
    assert "revenue" in prompt
    assert "cost" in prompt


def test_summary_prompt_includes_shape():
    df = pd.DataFrame({"a": range(100), "b": range(100)})
    prompt = build_summary_prompt(df)
    assert "100" in prompt
    assert "2" in prompt


def test_summary_prompt_includes_dtypes():
    df = pd.DataFrame({"name": ["Alice"], "age": [30]})
    prompt = build_summary_prompt(df)
    assert "object" in prompt or "string" in prompt
    assert "int" in prompt


def test_summary_prompt_includes_sample_rows():
    df = pd.DataFrame({"x": [1, 2, 3, 4, 5]})
    prompt = build_summary_prompt(df)
    assert "1" in prompt


def test_summary_prompt_includes_system_role():
    df = pd.DataFrame({"a": [1]})
    prompt = build_summary_prompt(df)
    assert "data" in prompt.lower()


def test_parse_valid_summary_response():
    raw = '''{
        "explanation": "This dataset contains sales data.",
        "cleaning_suggestions": [
            {"description": "3 duplicate rows found", "options": ["Remove", "Keep"]}
        ],
        "suggested_questions": ["What is the average revenue?", "Show the distribution of cost"]
    }'''
    parsed = parse_summary_response(raw)
    assert parsed["explanation"] == "This dataset contains sales data."
    assert len(parsed["cleaning_suggestions"]) == 1
    assert len(parsed["suggested_questions"]) == 2


def test_parse_response_missing_optional_fields():
    raw = '{"explanation": "Simple dataset."}'
    parsed = parse_summary_response(raw)
    assert parsed["explanation"] == "Simple dataset."
    assert parsed["cleaning_suggestions"] == []
    assert parsed["suggested_questions"] == []


def test_parse_malformed_json_returns_error():
    raw = "this is not json at all"
    parsed = parse_summary_response(raw)
    assert "error" in parsed
```

Run tests — all should fail:

```bash
cd backend
source venv/bin/activate
python -m pytest tests/test_llm.py -v
```

**Then Implementation:**

`llm.py` implements:
- `build_summary_prompt(df)` — constructs the system prompt with dataset metadata
- `parse_summary_response(raw)` — parses the LLM's JSON response
- `generate_summary(df, api_key)` — calls the OpenAI API and returns the parsed result

Update the `/api/upload` route in `main.py`: after creating the session, call `generate_summary()` and include the LLM-generated fields in the response.

Frontend: Build `FileUpload.tsx` (drag-and-drop or file picker, upload call, sheet selection for Excel). Build `DataSummary.tsx` (display metadata, cleaning suggestion cards, clickable suggested question chips).

**Verification:**

```bash
cd backend
source venv/bin/activate
python -m pytest tests/test_llm.py -v
```

**Expected output:** All 8 tests passing.

Manual verification: Upload a CSV in the browser. The summary screen should show row/column count, column info, data quality issues, cleaning suggestions, and suggested questions as clickable chips.

---

### Step 8 — Q&A Backend

**Goal:** Build the SSE-streaming `/api/chat` endpoint that takes a user question, constructs a prompt with dataset context and conversation history, calls the LLM, executes the generated code, and streams back the explanation and execution results. Includes conversation history management with sliding-window truncation to prevent token limit overflow.

**Files to create/modify:**

- `backend/llm.py` (modify — add chat prompt construction, response parsing, history truncation)
- `backend/main.py` (modify — add `/api/chat` SSE endpoint)
- `backend/tests/test_chat.py`
- `backend/tests/test_history_truncation.py`

**Tests FIRST:**

```python
"""
tests/test_chat.py

Tests for the chat endpoint and LLM-to-executor integration.

Behaviors tested:
- Chat endpoint returns an SSE stream
- SSE stream includes explanation events
- SSE stream includes result events with execution output
- SSE stream includes a done event
- Chat prompt includes the user's question
- Chat prompt includes conversation history
- Chat prompt includes dataset metadata
- Chat response parser extracts code and explanation
- Conversation history is updated after a successful exchange
"""
from unittest.mock import patch, AsyncMock, MagicMock
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from main import app
from llm import build_chat_prompt, parse_chat_response

client = TestClient(app)


def test_chat_prompt_includes_question():
    df = pd.DataFrame({"a": [1]})
    history = []
    prompt = build_chat_prompt("What is the mean of column a?", df, history)
    assert "mean" in prompt.lower() or "What is the mean" in prompt


def test_chat_prompt_includes_history():
    df = pd.DataFrame({"a": [1]})
    history = [{"role": "user", "content": "previous question"}]
    prompt = build_chat_prompt("follow up", df, history)
    assert "previous question" in prompt


def test_chat_prompt_includes_dataset_metadata():
    df = pd.DataFrame({"revenue": [100, 200], "cost": [50, 60]})
    prompt = build_chat_prompt("summarize", df, [])
    assert "revenue" in prompt
    assert "cost" in prompt


def test_parse_chat_response_extracts_code_and_explanation():
    raw = '{"code": "print(df.mean())", "explanation": "Calculating column means."}'
    parsed = parse_chat_response(raw)
    assert parsed["code"] == "print(df.mean())"
    assert parsed["explanation"] == "Calculating column means."


def test_parse_chat_response_with_cleaning_suggestions():
    raw = '''{
        "code": "print(df.isnull().sum())",
        "explanation": "Checking missing values.",
        "cleaning_suggestions": [{"description": "Column age has 10% missing", "options": ["Drop", "Fill median"]}]
    }'''
    parsed = parse_chat_response(raw)
    assert len(parsed["cleaning_suggestions"]) == 1
```

```python
"""
tests/test_history_truncation.py

Tests for conversation history sliding-window truncation.

Behaviors tested:
- History under the token limit is returned unchanged
- History over the token limit drops oldest messages first
- System prompt / dataset metadata is never truncated
- At least the most recent user message is always preserved
"""
from llm import truncate_history

# REVIEW: Token counting is approximate — using word count * 1.3 as a heuristic.
# If this causes premature truncation or token overflows, switch to tiktoken for exact counts.


def test_short_history_unchanged():
    history = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    result = truncate_history(history, max_tokens=10000)
    assert len(result) == 2


def test_long_history_drops_oldest():
    history = [{"role": "user", "content": f"message {i}" * 100} for i in range(50)]
    result = truncate_history(history, max_tokens=2000)
    assert len(result) < 50
    assert result[-1] == history[-1]


def test_most_recent_message_always_preserved():
    history = [{"role": "user", "content": "x" * 10000}]
    result = truncate_history(history, max_tokens=100)
    assert len(result) == 1
    assert result[0] == history[0]
```

Run tests — all should fail:

```bash
cd backend
source venv/bin/activate
python -m pytest tests/test_chat.py tests/test_history_truncation.py -v
```

**Then Implementation:**

Add to `llm.py`:
- `build_chat_prompt(question, df, history)` — constructs the chat prompt
- `parse_chat_response(raw)` — parses the LLM's JSON into code + explanation
- `truncate_history(history, max_tokens)` — sliding window that drops oldest messages when history exceeds the token budget, always preserving the most recent user message
- `generate_chat_response(question, session, api_key)` — orchestrates the LLM call with history truncation

Add to `main.py`:
- `/api/chat` POST endpoint that returns a `StreamingResponse` with SSE events: `explanation` (streamed tokens), `result` (execution output), `cleaning_suggestions` (if any), `error` (if execution fails), `done` (stream complete)

**Verification:**

```bash
cd backend
source venv/bin/activate
python -m pytest tests/test_chat.py tests/test_history_truncation.py -v
```

**Expected output:** All tests passing.

Manual verification with curl (replace the session ID from your upload response):

```bash
# First, upload a file to get a session ID:
SESSION_ID=$(curl -s -X POST http://localhost:8000/api/upload \
  -F "file=@test_data.csv" | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")

# Then, send a chat message:
curl -N -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"session_id\": \"$SESSION_ID\", \"question\": \"What is the average of each column?\"}"
```

**Expected output:** SSE events streamed to the terminal — `event: explanation` with text, `event: result` with execution output, `event: done`.

---

### Step 9 — Q&A Frontend

**Goal:** Build the chat UI that sends user questions, renders streaming responses, displays charts from base64 PNG data, and provides a code toggle to show/hide generated code.

**Files to create/modify:**

- `frontend/src/components/ChatPanel.tsx` (create)
- `frontend/src/components/MessageBubble.tsx` (create)
- `frontend/src/api.ts` (modify — add SSE client)
- `frontend/src/store.ts` (modify — add message state, streaming state)
- `frontend/src/App.tsx` (modify — wire chat screen)

**Tests FIRST (frontend — Vitest):**

```typescript
/**
 * Tests for chat UI behaviors.
 *
 * Behaviors tested:
 * - Sending a message adds it to the message list as a user message
 * - An assistant message renders explanation text
 * - An assistant message with figures renders images
 * - The code toggle shows/hides the generated code
 * - Suggested questions from initial summary are clickable and send as chat messages
 * - The input is disabled while streaming
 */
import { describe, it, expect } from 'vitest'
// Test implementations follow the behaviors above.
// Each test uses a testing library to render components and assert on DOM output.
```

Specific test cases and assertions to be refined during the TDD cycle (Step 2 of the test strategy — define specific test cases with the AI before writing code).

**Then Implementation:**

`ChatPanel.tsx` — message list (scrollable), text input with send button, disabled state during streaming.

`MessageBubble.tsx` — renders a single message. For assistant messages: explanation text, optional chart images (`<img src="data:image/png;base64,..." />`), optional code block behind a "Show code" toggle, optional cleaning suggestion cards.

`api.ts` — `sendChatMessage(sessionId, question)` function that opens an SSE connection to `/api/chat`, dispatches store updates as events arrive, and closes on `done`.

`store.ts` — add `addMessage`, `updateStreamingMessage`, `setStreaming` actions.

**Verification:**

```bash
cd frontend
npx vitest run
```

**Expected output:** All chat component tests passing.

Manual verification: Open the app, upload a dataset, click a suggested question. The chat should show the question, stream the response, display any charts, and offer a "Show code" toggle.

---

### Step 10 — Data Cleaning

**Goal:** Add interactive data cleaning with confirm-before-apply suggestions. Cleaning suggestions appear after upload, during analysis when relevant, and after cleaning actions. Each suggestion has options (e.g., "Drop rows / Fill with median"). No changes are applied without user confirmation.

**Files to create/modify (actual):**

- `backend/clean.py` (create — pure cleaning functions, extracted from route handler)
- `backend/main.py` (modify — add `/api/clean` and `/api/clean/reset` routes, `CleanRequest`/`ResetRequest` models)
- `backend/tests/test_clean.py` (create)
- `frontend/src/components/CleaningSuggestionCard.tsx` (create — replaces planned `CleaningPrompt.tsx`; shared by DataSummary and MessageBubble)
- `frontend/src/components/ChatPanel.tsx` (modify — header bar with reset button)
- `frontend/src/components/DataSummary.tsx` (modify — render upload-time cleaning suggestions)
- `frontend/src/components/MessageBubble.tsx` (modify — render chat-time cleaning suggestions)
- `frontend/src/store.ts` (modify — `hasAppliedCleaning`, `updateDatasetMetadata`, `CleaningSuggestion` type)
- `frontend/src/api.ts` (modify — `applyCleaningAction()`, `resetDatasets()`)

**Tests FIRST:**

```python
"""
Tests for the data cleaning endpoint.

Behaviors tested:
- Applying "drop duplicates" removes duplicate rows from the session dataframe
- Applying "fill missing with median" fills NaN values in the specified column
- Applying "drop rows with missing" removes rows with NaN in the specified column
- After cleaning, the response includes updated dataset stats
- After cleaning, the LLM is called to check for follow-up cleaning suggestions
- Cleaning with an invalid session ID returns 404
- Cleaning with an invalid action returns 400
"""
from unittest.mock import patch
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from main import app, session_store

client = TestClient(app)


def test_drop_duplicates_removes_dupes():
    df = pd.DataFrame({"a": [1, 1, 2], "b": [3, 3, 4]})
    session_id = session_store.create(df)
    response = client.post("/api/clean", json={
        "session_id": session_id,
        "action": "drop_duplicates",
    })
    assert response.status_code == 200
    session = session_store.get(session_id)
    assert len(session.dataframe) == 2


def test_fill_missing_with_median():
    df = pd.DataFrame({"age": [20.0, None, 40.0]})
    session_id = session_store.create(df)
    response = client.post("/api/clean", json={
        "session_id": session_id,
        "action": "fill_median",
        "column": "age",
    })
    assert response.status_code == 200
    session = session_store.get(session_id)
    assert session.dataframe["age"].isnull().sum() == 0


def test_drop_rows_with_missing():
    df = pd.DataFrame({"x": [1, None, 3], "y": [4, 5, 6]})
    session_id = session_store.create(df)
    response = client.post("/api/clean", json={
        "session_id": session_id,
        "action": "drop_missing",
        "column": "x",
    })
    assert response.status_code == 200
    session = session_store.get(session_id)
    assert len(session.dataframe) == 2


def test_clean_returns_updated_stats():
    df = pd.DataFrame({"a": [1, 1, 2]})
    session_id = session_store.create(df)
    response = client.post("/api/clean", json={
        "session_id": session_id,
        "action": "drop_duplicates",
    })
    data = response.json()
    assert "row_count" in data
    assert data["row_count"] == 2


def test_clean_invalid_session_returns_404():
    response = client.post("/api/clean", json={
        "session_id": "nonexistent",
        "action": "drop_duplicates",
    })
    assert response.status_code == 404


def test_clean_invalid_action_returns_400():
    df = pd.DataFrame({"a": [1]})
    session_id = session_store.create(df)
    response = client.post("/api/clean", json={
        "session_id": session_id,
        "action": "invalid_action",
    })
    assert response.status_code == 400
```

Run tests — all should fail:

```bash
cd backend
source venv/bin/activate
python -m pytest tests/test_clean.py -v
```

**Then Implementation:**

Backend: Add `/api/clean` POST route. Accepts `session_id`, `action`, and optional `column`. Performs the cleaning operation on the session's dataframe, updates the exec namespace, and optionally calls the LLM to check for follow-up suggestions.

Frontend: Build `CleaningPrompt.tsx` — renders a card with the suggestion description and option buttons. On click, calls `/api/clean` with the chosen action. On response, updates the dataset info and renders any follow-up suggestions.

**Verification:**

```bash
cd backend
source venv/bin/activate
python -m pytest tests/test_clean.py -v
```

**Expected output:** All 6 tests passing.

Manual verification: Upload a dataset with duplicates or missing values. Click a cleaning suggestion. Confirm the action is applied and updated stats are shown.

---

### Step 11 — Error Recovery

**Goal:** When LLM-generated code fails to execute, the system retries automatically by re-prompting the LLM with the error context. If the retry also fails, the user sees a plain-English error explanation and a suggestion to rephrase.

**Files to create/modify:**

- `backend/main.py` (modify — retry orchestration: `_single_chat_attempt`, `_attempt_chat_with_retries`, `MAX_CHAT_RETRIES`)
- `backend/llm.py` (modify — pure retry prompt builder: `build_retry_messages`, `TIMEOUT_RETRY_GUIDANCE`)
- `backend/tests/test_error_recovery.py`
- `frontend/src/components/MessageBubble.tsx` (modify — friendly error display with collapsible details)

**Tests FIRST:**

```python
"""
Tests for error recovery and retry logic.

Behaviors tested:
- On first execution failure, the LLM is re-prompted with the error traceback
- If retry succeeds, the successful result is returned
- If retry also fails, an error is returned with a plain-English explanation
- The error message sent to the LLM includes the original code and traceback
- Maximum retry count is 1 (original + 1 retry)
"""
from unittest.mock import patch, MagicMock, AsyncMock, call
import pytest
from llm import generate_chat_response_with_retry


@pytest.mark.asyncio
async def test_retry_on_first_failure():
    """If the first code execution fails, the LLM is called again with the error."""
    with patch("llm.call_llm") as mock_llm, \
         patch("llm.execute_code") as mock_exec:
        mock_llm.side_effect = [
            '{"code": "bad code", "explanation": "trying"}',
            '{"code": "print(1)", "explanation": "fixed"}',
        ]
        mock_exec.side_effect = [
            {"error": "NameError: name 'bad' is not defined", "stdout": "", "figures": []},
            {"error": None, "stdout": "1", "figures": []},
        ]
        result = await generate_chat_response_with_retry("question", MagicMock(), "key")
        assert result["error"] is None
        assert mock_llm.call_count == 2


@pytest.mark.asyncio
async def test_double_failure_returns_error():
    """If both attempts fail, return an error with explanation."""
    with patch("llm.call_llm") as mock_llm, \
         patch("llm.execute_code") as mock_exec:
        mock_llm.return_value = '{"code": "bad", "explanation": "trying"}'
        mock_exec.return_value = {"error": "SomeError", "stdout": "", "figures": []}
        result = await generate_chat_response_with_retry("question", MagicMock(), "key")
        assert result["error"] is not None
        assert mock_llm.call_count == 2


@pytest.mark.asyncio
async def test_retry_prompt_includes_error_context():
    """The retry prompt should include the original code and traceback."""
    with patch("llm.call_llm") as mock_llm, \
         patch("llm.execute_code") as mock_exec:
        mock_llm.side_effect = [
            '{"code": "df.nonexistent()", "explanation": "trying"}',
            '{"code": "print(1)", "explanation": "fixed"}',
        ]
        mock_exec.side_effect = [
            {"error": "AttributeError: no attribute 'nonexistent'", "stdout": "", "figures": []},
            {"error": None, "stdout": "1", "figures": []},
        ]
        await generate_chat_response_with_retry("question", MagicMock(), "key")
        retry_call_args = mock_llm.call_args_list[1]
        prompt = str(retry_call_args)
        assert "nonexistent" in prompt or "AttributeError" in prompt
```

Run tests — all should fail:

```bash
cd backend
source venv/bin/activate
python -m pytest tests/test_error_recovery.py -v
```

**Then Implementation:**

Backend: Add `generate_chat_response_with_retry()` to `llm.py`. This wraps the normal chat flow: call LLM → execute code → if error, append error context to conversation and call LLM again → if second error, return plain-English error. Update the `/api/chat` endpoint to use this function.

Frontend: Update `MessageBubble.tsx` to render error events with a friendly message (e.g., "I couldn't execute the analysis. Try rephrasing your question or being more specific.") styled distinctly from normal responses.

**Verification:**

```bash
cd backend
source venv/bin/activate
python -m pytest tests/test_error_recovery.py -v
```

**Expected output:** All 3 tests passing.

Manual verification: Ask a question that's likely to produce a code error (e.g., "Plot the column that doesn't exist"). The system should retry once and, if both fail, show a friendly error message.

---

### Step 12 — Guided ML Backend ✅ Done

**Goal:** Build the backend prompt chains that drive the step-by-step ML workflow: target selection, feature selection, preprocessing, model selection, training/evaluation, and explanation. Each step produces a specific prompt and expects a structured response.

**Files to create/modify:**

- `backend/llm.py` (modify — add ML workflow prompt builders and response parsers)
- `backend/main.py` (modify — add `/api/ml-step` endpoint or extend `/api/chat`)
- `backend/tests/test_ml_workflow.py`

**Tests FIRST:**

```python
"""
Tests for the guided ML workflow prompt chains.

Behaviors tested:
- Target selection prompt includes all column names as options
- Feature selection prompt includes correlation data and suggested features
- Preprocessing prompt handles encoding, scaling, and missing value decisions
- Model selection prompt suggests appropriate models based on problem type (classification vs regression)
- Training prompt generates code that fits a model and produces evaluation metrics
- Each ML step response parser extracts the expected structured fields
- Problem type is correctly inferred as classification for categorical targets
- Problem type is correctly inferred as regression for numeric targets
"""
import pandas as pd
import pytest
from llm import (
    build_target_selection_prompt,
    build_feature_selection_prompt,
    build_model_selection_prompt,
    parse_ml_step_response,
    infer_problem_type,
)


def test_target_prompt_includes_all_columns():
    df = pd.DataFrame({"price": [1], "size": [2], "color": ["red"]})
    prompt = build_target_selection_prompt(df)
    assert "price" in prompt
    assert "size" in prompt
    assert "color" in prompt


def test_feature_prompt_includes_suggested_features():
    df = pd.DataFrame({"target": [1, 0, 1], "feat1": [10, 20, 30], "feat2": [5, 5, 5]})
    prompt = build_feature_selection_prompt(df, target_column="target")
    assert "feat1" in prompt
    assert "feat2" in prompt


def test_model_selection_classification():
    df = pd.DataFrame({"target": ["cat", "dog", "cat"]})
    prompt = build_model_selection_prompt(df, target_column="target", features=["a"])
    assert "classification" in prompt.lower()


def test_model_selection_regression():
    df = pd.DataFrame({"target": [1.5, 2.3, 4.1]})
    prompt = build_model_selection_prompt(df, target_column="target", features=["a"])
    assert "regression" in prompt.lower()


def test_infer_problem_type_categorical():
    df = pd.DataFrame({"target": ["yes", "no", "yes"]})
    assert infer_problem_type(df, "target") == "classification"


def test_infer_problem_type_numeric():
    df = pd.DataFrame({"target": [1.0, 2.5, 3.7]})
    assert infer_problem_type(df, "target") == "regression"


def test_infer_problem_type_few_unique_ints():
    df = pd.DataFrame({"target": [0, 1, 0, 1, 0]})
    assert infer_problem_type(df, "target") == "classification"


def test_parse_ml_step_response():
    raw = '{"code": "model.fit(X, y)", "explanation": "Training a random forest.", "step": "training"}'
    parsed = parse_ml_step_response(raw)
    assert parsed["code"] == "model.fit(X, y)"
    assert parsed["step"] == "training"
```

Run tests — all should fail:

```bash
cd backend
source venv/bin/activate
python -m pytest tests/test_ml_workflow.py -v
```

**Then Implementation:**

Add ML-specific prompt builders to `llm.py`:
- `build_target_selection_prompt(df)` — asks the LLM to help the user choose a target column
- `build_feature_selection_prompt(df, target_column)` — includes correlation analysis
- `build_model_selection_prompt(df, target_column, features)` — suggests models based on problem type
- `infer_problem_type(df, target_column)` — heuristic: categorical/few-unique-int → classification, otherwise regression
- `parse_ml_step_response(raw)` — parses ML step responses

Add `/api/ml-step` endpoint (or extend chat) to handle the wizard flow. The endpoint accepts a `step` parameter and the user's choices for that step.

**Verification:**

```bash
cd backend
source venv/bin/activate
python -m pytest tests/test_ml_workflow.py -v
```

**Expected output:** All 8 tests passing.

---

### Step 13 — Guided ML Frontend ✅ Done

**Goal:** Build the wizard-style UI that walks the user through the ML workflow step by step. Each step presents options or information and waits for user input before proceeding.

**Files to create/modify:**

- `frontend/src/components/MLWizard.tsx` (create)
- `frontend/src/store.ts` (modify — add ML wizard state)
- `frontend/src/api.ts` (modify — add ML step API calls)
- `frontend/src/App.tsx` (modify — trigger wizard from chat)

**Tests FIRST (frontend — Vitest):**

```typescript
/**
 * Tests for the ML wizard UI.
 *
 * Behaviors tested:
 * - Target selection step renders column names as selectable options
 * - Selecting a target and confirming advances to feature selection
 * - Feature selection shows suggested features with checkboxes
 * - The wizard does not advance without user confirmation at each step
 * - Training step shows a loading state while the model trains
 * - Results step displays evaluation metrics
 */
import { describe, it, expect } from 'vitest'
// Test implementations follow the behaviors above.
```

Specific test cases to be refined during the TDD cycle.

**Then Implementation:**

`MLWizard.tsx` — a multi-step component that renders different content based on the current wizard step. Each step shows the LLM's suggestion/explanation and provides input controls (dropdowns, checkboxes, confirm buttons). The wizard state tracks `currentStep`, `targetColumn`, `selectedFeatures`, `selectedModel`, and `results`.

The wizard is triggered when the user says something like "I want to build a model" or "predict [column]" — the chat handler detects ML intent and transitions to the wizard flow.

**Verification:**

```bash
cd frontend
npx vitest run
```

**Expected output:** All ML wizard tests passing.

Manual verification: Upload a dataset, say "I want to predict the price column." The wizard should walk through target → features → preprocessing → model → training → results, waiting for confirmation at each step.

---

### Step 14 — Export ✅ Done

**Goal:** Build the notebook exporter that converts a session's code history into a downloadable Jupyter notebook (`.ipynb`), and add a download button to the chat UI.

**Files to create/modify:**

- `backend/exporter.py` (create)
- `backend/main.py` (modify — add `/api/export/{session_id}` route)
- `backend/tests/test_exporter.py`
- `frontend/src/components/ChatPanel.tsx` (modify — add export button)

**Tests FIRST:**

```python
"""
Tests for notebook export.

Behaviors tested:
- Exported notebook is valid JSON
- Exported notebook contains a header cell with imports
- Each code history entry becomes a code cell + markdown cell
- Code cells contain the generated code
- Markdown cells contain the plain-English explanation
- Exported notebook includes dataset loading cell
- Export with empty history returns a notebook with just header and data loading cells
"""
import json
import pytest
from exporter import build_notebook


def test_notebook_is_valid_json():
    history = [{"code": "print(1)", "explanation": "Prints one."}]
    notebook = build_notebook(history, "data.csv")
    parsed = json.loads(json.dumps(notebook))
    assert parsed["nbformat"] == 4


def test_notebook_has_header_cell():
    notebook = build_notebook([], "data.csv")
    first_cell = notebook["cells"][0]
    assert first_cell["cell_type"] == "code"
    source = "".join(first_cell["source"])
    assert "import pandas" in source


def test_notebook_has_data_loading_cell():
    notebook = build_notebook([], "data.csv")
    cells_source = ["".join(c["source"]) for c in notebook["cells"]]
    assert any("data.csv" in s for s in cells_source)


def test_code_history_becomes_cells():
    history = [
        {"code": "print(df.head())", "explanation": "Show first rows."},
        {"code": "print(df.describe())", "explanation": "Summary statistics."},
    ]
    notebook = build_notebook(history, "data.csv")
    code_cells = [c for c in notebook["cells"] if c["cell_type"] == "code"]
    md_cells = [c for c in notebook["cells"] if c["cell_type"] == "markdown"]
    # Header + data loading + 2 code entries = 4 code cells
    assert len(code_cells) >= 4
    assert len(md_cells) >= 2


def test_code_cell_contains_generated_code():
    history = [{"code": "df['new'] = df['a'] + 1", "explanation": "Add column."}]
    notebook = build_notebook(history, "data.csv")
    code_cells = [c for c in notebook["cells"] if c["cell_type"] == "code"]
    all_code = " ".join("".join(c["source"]) for c in code_cells)
    assert "df['new'] = df['a'] + 1" in all_code


def test_markdown_cell_contains_explanation():
    history = [{"code": "print(1)", "explanation": "This prints the number one."}]
    notebook = build_notebook(history, "data.csv")
    md_cells = [c for c in notebook["cells"] if c["cell_type"] == "markdown"]
    all_md = " ".join("".join(c["source"]) for c in md_cells)
    assert "This prints the number one." in all_md


def test_empty_history_returns_minimal_notebook():
    notebook = build_notebook([], "data.csv")
    assert len(notebook["cells"]) >= 2  # header + data loading
```

Run tests — all should fail:

```bash
cd backend
source venv/bin/activate
python -m pytest tests/test_exporter.py -v
```

**Then Implementation:**

`exporter.py` implements `build_notebook(code_history, filename)`:
- Builds the `.ipynb` JSON structure (nbformat 4)
- Header code cell with imports (`pandas`, `numpy`, `matplotlib`, `seaborn`, `sklearn`)
- Data loading cell (`df = pd.read_csv("data.csv")`)
- For each code history entry: a markdown cell with the explanation, then a code cell with the generated code

Add `/api/export/{session_id}` GET route to `main.py` that calls `build_notebook()` and returns the file as a download response with content type `application/x-ipynb+json`.

Frontend: Add an "Export Notebook" button to `ChatPanel.tsx` that triggers a download via the export endpoint.

**Verification:**

```bash
cd backend
source venv/bin/activate
python -m pytest tests/test_exporter.py -v
```

**Expected output:** All 7 tests passing.

Manual verification: Upload a dataset, ask a few questions, then click the export button. Open the downloaded `.ipynb` in Jupyter and verify it runs without errors.

---

### Step 15 — Help

**Goal:** Add a help modal accessible from any screen that explains the tool's capabilities, how to get started, example questions to ask, and how to obtain an API key.

**Files to create/modify:**

- `frontend/src/components/HelpModal.tsx` (create)
- `frontend/src/App.tsx` (modify — add help button)

**Step order:** Frontend-only, no backend changes. No TDD cycle needed — this is static content with a simple open/close interaction.

**Implementation:**

`HelpModal.tsx` — a modal overlay triggered by a help button (e.g., `?` icon) visible on all screens. Content includes:
- What the tool does (1–2 sentences)
- How to get started (enter API key → upload dataset → ask questions)
- Example questions ("What is the distribution of age?", "Are there correlations between price and rating?", "Show me the outliers in revenue")
- How to obtain an OpenAI API key (link to platform.openai.com)
- How to export your work as a notebook

The help button should be positioned consistently (e.g., top-right corner) across all screens.

**Verification:**

Manual verification: On every screen (setup, upload, chat), click the help button. The modal should open, display all content, and close when dismissed.

---

## Deferred Features

| Feature | Deferred to | Notes |
|---------|-------------|-------|
| Anthropic provider support | ~~Post-MVP~~ **Done in Step 6** | Both OpenAI and Anthropic are supported from Step 6. `llm.py` (Step 7) must dispatch on `session.provider` when constructing API calls. |
| Multi-dataset joins | Not planned | PRD non-goal |
| User accounts / persistence | Not planned | PRD non-goal |
| CI pipeline | Post-MVP | Test suite runs locally; CI setup is a follow-up task |
| Session timeout / cleanup | Post-MVP | Acceptable for prototype — restart server to reclaim memory |
| File size validation UX | Post-MVP | Backend rejects > 50MB; frontend could show a preemptive warning |

---

## Integration Test Suite (LLM)

Separate from the unit test suite. These tests hit the real OpenAI API and are skipped by default (require `OPENAI_API_KEY` env var).

**Location:** `backend/tests/integration/`

**Running:**

```bash
cd backend
source venv/bin/activate
OPENAI_API_KEY=sk-... python -m pytest tests/integration/ -v
```

**Tests use loose assertions:**
- Response contains valid JSON with `code` and `explanation` fields
- Generated code is syntactically valid Python
- Execution of generated code does not crash on a sample dataset

These tests are added incrementally alongside Steps 7, 8, and 12 as each LLM-powered feature is built.
