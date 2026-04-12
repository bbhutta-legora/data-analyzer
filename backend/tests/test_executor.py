# tests/test_executor.py
# Tests for sandboxed code execution.
# Related module: backend/executor.py
# PRD: supports #3 (Q&A code execution) and #5 (guided ML)
#
# Design note: most tests call _execute_in_sandbox() directly (synchronously, same process)
# to avoid subprocess spawning in tests. The timeout test is the only one that calls
# execute_code() with a real subprocess — if it fails in a sandboxed CI environment,
# mark it as an integration test. See harness/coding_principles.md §Testing Parallel/Multiprocessing Code.
#
# Namespace model: the sandbox receives a pickled dict[str, pd.DataFrame] as 'dfs'.
# LLM-generated code references DataFrames as dfs["name"], not df.
#
# Confirmed behavior list (TEST-STRATEGY Steps 1–2):
# Stdout:   1. print() output is captured in result["stdout"]
# Figures:  2. A matplotlib figure is captured as a base64 PNG
#           3. Multiple figures are all captured
# Df track: 4. Adding a column to a named DataFrame sets dataframe_changed True
#           5. Reassigning a named DataFrame to fewer rows sets dataframe_changed True
#           6. Code that doesn't touch dfs leaves dataframe_changed False
# Errors:   7. A syntax error returns an error containing "SyntaxError"
#           8. A runtime error returns an error containing the exception name
# Security: 9. import os is blocked and returns an error
#           10. open() is blocked and returns an error
#           11. Pre-loaded libraries (pd, np, etc.) remain accessible
# Timeout:  12. An infinite loop with a 2s timeout returns a timeout error

import base64
import pickle

import pandas as pd
import pytest

from executor import _execute_in_sandbox, execute_code


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]})


@pytest.fixture
def sample_dfs(sample_df) -> dict[str, pd.DataFrame]:
    return {"data": sample_df}


@pytest.fixture
def sample_dfs_pickle(sample_dfs) -> bytes:
    return pickle.dumps(sample_dfs)


# ── Stdout capture ────────────────────────────────────────────────────────────

def test_execute_captures_stdout(sample_dfs_pickle):
    # When the code is print('hello world'), result should contain "hello world" in stdout and no error.
    result = _execute_in_sandbox("print('hello world')", sample_dfs_pickle)
    assert result["error"] is None
    assert "hello world" in result["stdout"]


# ── Figure capture ────────────────────────────────────────────────────────────

def test_execute_captures_single_figure_as_base64_png(sample_dfs_pickle):
    # When code creates one matplotlib figure, result should contain 1 figure that decodes to a valid PNG.
    code = "plt.figure()\nplt.plot([1, 2, 3], [4, 5, 6])"
    result = _execute_in_sandbox(code, sample_dfs_pickle)
    assert result["error"] is None
    assert len(result["figures"]) == 1
    decoded = base64.b64decode(result["figures"][0])
    assert decoded[:4] == b'\x89PNG'


def test_execute_captures_multiple_figures(sample_dfs_pickle):
    # When code creates two separate figures with two plt.figure() calls,
    # result should contain exactly 2 figures.
    code = "plt.figure()\nplt.plot([1, 2], [3, 4])\nplt.figure()\nplt.bar([1, 2], [3, 4])"
    result = _execute_in_sandbox(code, sample_dfs_pickle)
    assert result["error"] is None
    assert len(result["figures"]) == 2


# ── Dataframe tracking ────────────────────────────────────────────────────────

def test_execute_column_addition_sets_dataframe_changed(sample_dfs_pickle):
    # When code adds a column to a named DataFrame,
    # result should report dataframe_changed as True.
    result = _execute_in_sandbox("dfs['data']['z'] = dfs['data']['x'] + dfs['data']['y']", sample_dfs_pickle)
    assert result["error"] is None
    assert result["dataframe_changed"] is True


def test_execute_row_reduction_sets_dataframe_changed(sample_dfs_pickle):
    # When code reassigns a named DataFrame to fewer rows,
    # result should report dataframe_changed as True.
    result = _execute_in_sandbox("dfs['data'] = dfs['data'].head(1)", sample_dfs_pickle)
    assert result["error"] is None
    assert result["dataframe_changed"] is True


def test_execute_no_df_touch_leaves_dataframe_unchanged(sample_dfs_pickle):
    # When code doesn't touch dfs at all (e.g. x = 1 + 1),
    # result should report dataframe_changed as False.
    result = _execute_in_sandbox("x = 1 + 1", sample_dfs_pickle)
    assert result["error"] is None
    assert result["dataframe_changed"] is False


# ── Error handling ────────────────────────────────────────────────────────────

def test_execute_syntax_error_returns_error(sample_dfs_pickle):
    # When code has a syntax error like def foo(,
    # result should contain "SyntaxError" in the error field.
    result = _execute_in_sandbox("def foo(", sample_dfs_pickle)
    assert result["error"] is not None
    assert "SyntaxError" in result["error"]


def test_execute_runtime_error_returns_error(sample_dfs_pickle):
    # When code raises a runtime error like 1 / 0,
    # result should contain "ZeroDivisionError" in the error field.
    result = _execute_in_sandbox("1 / 0", sample_dfs_pickle)
    assert result["error"] is not None
    assert "ZeroDivisionError" in result["error"]


# ── Security ──────────────────────────────────────────────────────────────────

def test_execute_blocks_import(sample_dfs_pickle):
    # When code tries import os, it should be blocked and result should contain an error.
    # Mechanism: __import__ is removed from __builtins__, so the import statement has
    # no function to call and raises ImportError or NameError.
    result = _execute_in_sandbox("import os", sample_dfs_pickle)
    assert result["error"] is not None


def test_execute_blocks_open(sample_dfs_pickle):
    # When code tries open('/etc/passwd'), it should be blocked and result should contain an error.
    result = _execute_in_sandbox("open('/etc/passwd')", sample_dfs_pickle)
    assert result["error"] is not None


def test_execute_preloaded_libraries_remain_accessible(sample_dfs_pickle):
    # When code uses a pre-loaded library like pd.DataFrame({'a': [1]}),
    # it should work with no error — the sandbox blocks new imports, not pre-loaded ones.
    result = _execute_in_sandbox(
        "x = pd.DataFrame({'a': [1]})\nprint(x.shape)",
        sample_dfs_pickle,
    )
    assert result["error"] is None
    assert "(1, 1)" in result["stdout"]


# ── Timeout ───────────────────────────────────────────────────────────────────

def test_execute_timeout_kills_long_running_code(sample_df):
    # When code runs an infinite loop with a 2-second timeout,
    # result should contain "timed out" in the error field.
    result = execute_code("while True: pass", {"dfs": {"data": sample_df}}, timeout=2)
    assert result["error"] is not None
    assert "timed out" in result["error"].lower()
