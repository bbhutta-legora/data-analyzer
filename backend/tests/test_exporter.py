# tests/test_exporter.py
# Tests for the notebook export feature (Step 14).
# Related modules: backend/exporter.py (pure logic), backend/main.py (/api/export route)
# PRD ref: #7 (Export)
#
# Behaviors tested:
#  1. build_notebook() with empty code_history produces a notebook with header + data-loading cells
#  2. build_notebook() with code history entries produces paired markdown + code cells
#  3. Notebook has correct nbformat version (4) and nbformat_minor (5)
#  4. Data-loading cell references the correct filename
#  5. Header cell contains all expected library imports
#  6. Code cells contain the generated code from history
#  7. Markdown cells contain the plain-English explanation from history
#  8. /api/export/{session_id} returns 200 with correct content-type for valid session
#  9. /api/export/{session_id} returns 404 for unknown session
# 10. Response filename is derived from uploaded file

import io
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from exporter import build_notebook
from main import app, session_store

client = TestClient(app)


# ── Pure function tests (build_notebook) ─────────────────────────────────────


def test_empty_history_returns_notebook_with_header_and_loading_cells():
    """Behavior 1: empty code_history produces just header + data-loading cells."""
    notebook = build_notebook([], "sales.csv")
    assert len(notebook["cells"]) == 2
    assert notebook["cells"][0]["cell_type"] == "code"
    assert notebook["cells"][1]["cell_type"] == "code"


def test_code_history_produces_paired_markdown_and_code_cells():
    """Behavior 2: each history entry becomes a markdown cell then a code cell."""
    history = [
        {"code": "print(df.head())", "explanation": "Show first rows."},
        {"code": "print(df.describe())", "explanation": "Summary statistics."},
    ]
    notebook = build_notebook(history, "data.csv")
    # 2 header/loading cells + 2 * (markdown + code) = 6 total
    assert len(notebook["cells"]) == 6
    # After the 2 header cells, pairs should alternate markdown then code
    assert notebook["cells"][2]["cell_type"] == "markdown"
    assert notebook["cells"][3]["cell_type"] == "code"
    assert notebook["cells"][4]["cell_type"] == "markdown"
    assert notebook["cells"][5]["cell_type"] == "code"


def test_notebook_has_correct_nbformat_version():
    """Behavior 3: notebook declares nbformat 4, nbformat_minor 5."""
    notebook = build_notebook([], "data.csv")
    assert notebook["nbformat"] == 4
    assert notebook["nbformat_minor"] == 5


def test_data_loading_cell_references_correct_filename():
    """Behavior 4: the data-loading cell references the uploaded filename."""
    notebook = build_notebook([], "quarterly_sales.csv")
    loading_cell = notebook["cells"][1]
    source = "".join(loading_cell["source"])
    assert "quarterly_sales.csv" in source


def test_header_cell_contains_expected_imports():
    """Behavior 5: header cell imports pandas, numpy, matplotlib, seaborn, sklearn."""
    notebook = build_notebook([], "data.csv")
    header_source = "".join(notebook["cells"][0]["source"])
    assert "import pandas as pd" in header_source
    assert "import numpy as np" in header_source
    assert "import matplotlib.pyplot as plt" in header_source
    assert "import seaborn as sns" in header_source
    assert "import sklearn" in header_source


def test_code_cell_contains_generated_code():
    """Behavior 6: code cells contain the exact code from history entries."""
    history = [{"code": "df['new'] = df['a'] + 1", "explanation": "Add column."}]
    notebook = build_notebook(history, "data.csv")
    # The analysis code cell is the 3rd cell (index 2 = markdown, index 3 = code)
    code_cell = notebook["cells"][3]
    source = "".join(code_cell["source"])
    assert "df['new'] = df['a'] + 1" in source


def test_markdown_cell_contains_explanation():
    """Behavior 7: markdown cells contain the explanation text from history entries."""
    history = [{"code": "print(1)", "explanation": "This prints the number one."}]
    notebook = build_notebook(history, "data.csv")
    md_cell = notebook["cells"][2]
    source = "".join(md_cell["source"])
    assert "This prints the number one." in source


def test_notebook_is_valid_json_roundtrip():
    """The notebook dict survives a JSON serialize/deserialize roundtrip."""
    history = [{"code": "print(1)", "explanation": "Prints one."}]
    notebook = build_notebook(history, "data.csv")
    roundtripped = json.loads(json.dumps(notebook))
    assert roundtripped["nbformat"] == 4
    assert len(roundtripped["cells"]) == len(notebook["cells"])


def test_notebook_metadata_has_python_kernelspec():
    """Notebook metadata includes a Python 3 kernelspec so Jupyter opens it correctly."""
    notebook = build_notebook([], "data.csv")
    assert "kernelspec" in notebook["metadata"]
    assert notebook["metadata"]["kernelspec"]["language"] == "python"


def test_history_entry_with_empty_code_produces_only_markdown_cell():
    """A history entry with empty code should still produce a markdown cell but skip the code cell."""
    history = [{"code": "", "explanation": "Just an explanation, no code."}]
    notebook = build_notebook(history, "data.csv")
    # 2 base cells + 1 markdown (no code cell since code is empty) = 3
    assert len(notebook["cells"]) == 3
    assert notebook["cells"][2]["cell_type"] == "markdown"


# ── Route tests (/api/export/{session_id}) ───────────────────────────────────


@pytest.fixture
def session_with_history() -> str:
    """Create a session with some code history and return the session_id."""
    df = pd.DataFrame({"x": [1, 2, 3]})
    session_id = session_store.create(
        {"test": df}, original_filename="sales.csv",
    )
    session = session_store.get(session_id)
    session.code_history.append({
        "code": "print(df.head())",
        "explanation": "Show first rows.",
    })
    return session_id


def test_export_route_returns_200_with_correct_content_type(session_with_history):
    """Behavior 8: valid session returns 200 with application/x-ipynb+json."""
    response = client.get(f"/api/export/{session_with_history}")
    assert response.status_code == 200
    assert "application/x-ipynb+json" in response.headers["content-type"]


def test_export_route_returns_404_for_unknown_session():
    """Behavior 9: unknown session_id returns 404."""
    response = client.get("/api/export/nonexistent-session-id")
    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "session_not_found"


def test_export_route_filename_derived_from_uploaded_file(session_with_history):
    """Behavior 10: Content-Disposition filename is derived from original_filename."""
    response = client.get(f"/api/export/{session_with_history}")
    content_disp = response.headers["content-disposition"]
    assert "sales_analysis.ipynb" in content_disp


def test_export_route_response_is_valid_notebook_json(session_with_history):
    """The response body is a valid notebook JSON with cells from the session."""
    response = client.get(f"/api/export/{session_with_history}")
    notebook = response.json()
    assert notebook["nbformat"] == 4
    assert len(notebook["cells"]) > 0


# ── Edge-case tests (audit gaps) ────────────────────────────────────────────


def test_empty_filename_uses_fallback():
    """Empty original_filename → data-loading cell uses 'data.csv', not an empty string."""
    notebook = build_notebook([], "")
    loading_cell = notebook["cells"][1]
    source = "".join(loading_cell["source"])
    assert "data.csv" in source
    assert "read_csv('')" not in source


def test_filename_with_spaces_produces_valid_python():
    """Filename with spaces → data-loading cell produces valid Python."""
    notebook = build_notebook([], "my data file.csv")
    loading_cell = notebook["cells"][1]
    source = "".join(loading_cell["source"])
    assert "my data file.csv" in source
    # Verify it's syntactically valid Python
    compile(source, "<test>", "exec")


def test_filename_with_quotes_produces_valid_python():
    """Filename with double and single quotes → data-loading cell produces valid Python."""
    notebook = build_notebook([], 'data "v2".csv')
    loading_cell = notebook["cells"][1]
    source = "".join(loading_cell["source"])
    compile(source, "<test>", "exec")
    assert "v2" in source

    # Also test single quotes
    notebook2 = build_notebook([], "data 'v3'.csv")
    loading_cell2 = notebook2["cells"][1]
    source2 = "".join(loading_cell2["source"])
    compile(source2, "<test>", "exec")
    assert "v3" in source2


def test_code_history_entry_with_empty_explanation():
    """Entry with empty explanation → only code cell produced, no crash."""
    history = [{"code": "print(1)", "explanation": ""}]
    notebook = build_notebook(history, "data.csv")
    # 2 base cells + 1 code cell (no markdown because explanation is empty)
    assert len(notebook["cells"]) == 3
    assert notebook["cells"][2]["cell_type"] == "code"


def test_code_history_entry_with_missing_explanation_key():
    """Entry missing 'explanation' key entirely → doesn't crash."""
    history = [{"code": "print(1)"}]
    notebook = build_notebook(history, "data.csv")
    # 2 base cells + 1 code cell
    assert len(notebook["cells"]) == 3
    assert notebook["cells"][2]["cell_type"] == "code"


def test_code_with_backslashes_and_unicode_survives_json_roundtrip():
    """Code with backslashes and unicode → survives JSON serialize/deserialize."""
    code = 'path = "C:\\\\Users\\\\data"\nprint("héllo 世界")'
    history = [{"code": code, "explanation": "Paths and unicode."}]
    notebook = build_notebook(history, "data.csv")
    roundtripped = json.loads(json.dumps(notebook))
    code_cell = roundtripped["cells"][3]  # index 0=header, 1=loading, 2=md, 3=code
    assert "".join(code_cell["source"]) == code


def test_empty_code_history_returns_valid_notebook_with_header_and_loading():
    """Endpoint with empty code_history → returns valid notebook with header + data-loading cells."""
    df = pd.DataFrame({"x": [1]})
    sid = session_store.create({"test": df}, original_filename="empty.csv")
    # Ensure code_history is empty (it should be by default)
    session = session_store.get(sid)
    assert session.code_history == []

    response = client.get(f"/api/export/{sid}")
    assert response.status_code == 200
    notebook = response.json()
    assert notebook["nbformat"] == 4
    assert len(notebook["cells"]) == 2
    assert notebook["cells"][0]["cell_type"] == "code"
    assert notebook["cells"][1]["cell_type"] == "code"
    assert "empty.csv" in "".join(notebook["cells"][1]["source"])
