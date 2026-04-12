# executor.py
# Runs LLM-generated Python code in a restricted, sandboxed child process.
# Supports: PRD #3 (Q&A code execution), #4 (data cleaning), #5 (guided ML)
# Key deps: multiprocessing (cross-platform process isolation + kill on timeout),
#           pickle (serialise DataFrame across process boundary),
#           matplotlib (figure capture as base64 PNG)
#
# Architecture: three-function design.
#   _execute_in_sandbox() — pure worker logic; all heavy imports inside; callable directly in tests.
#   _worker_process()     — thin entry point for multiprocessing.Process; calls _execute_in_sandbox
#                           and sends the result back through a Pipe.
#   execute_code()        — public API; spawns child process, enforces timeout, kills on overrun.
#
# Tests: backend/tests/test_executor.py
# Cross-platform: uses multiprocessing.Process + Pipe (no SIGALRM, no semaphores);
#   child process is killed with process.kill() on timeout.
#   See harness/coding_principles.md §Cross-Platform.

import multiprocessing
import pickle

DEFAULT_EXECUTION_TIMEOUT_SECONDS = 60

# Builtins that must be removed from the sandboxed namespace to prevent filesystem
# access, network calls, and arbitrary code loading.
# REVIEW: blocklist approach — any new dangerous builtin added in a future Python release
# would be allowed by default. Evaluate switching to an allowlist if the threat model grows.
_BLOCKED_BUILTINS = frozenset({
    "__import__",
    "open",
    "eval",
    "exec",
    "compile",
    "globals",
    "locals",
})


def _detect_dataframe_change(
    original_shape: tuple,
    original_columns: list,
    new_df: object,
) -> bool:
    """
    Fast change detection using shape and column list instead of .equals().

    Returns True if the dataframe's shape or columns changed, or if df was replaced
    with a non-DataFrame object. Does not detect value-level changes (e.g. a single
    cell being overwritten) — those are acceptable to miss for this use case.
    """
    has_shape = hasattr(new_df, "shape")
    has_columns = hasattr(new_df, "columns")

    if not has_shape or not has_columns:
        return True

    return new_df.shape != original_shape or list(new_df.columns) != original_columns


def _execute_in_sandbox(code: str, df_pickle: bytes) -> dict:
    """
    Execute code in a sandboxed namespace and return structured results.

    All heavy imports are performed inside this function so it initialises correctly
    when spawned as a child process.

    This function is also called directly in unit tests (synchronously, same process)
    to avoid subprocess-spawning complexity. See test_executor.py for usage.

    Failure modes:
    - SyntaxError in user code → result["error"] contains the traceback
    - Runtime exception in user code → result["error"] contains the traceback
    - Blocked builtin called → result["error"] contains ImportError/NameError traceback

    Returns dict with keys:
        stdout          (str)       — captured print() output
        figures         (list[str]) — base64-encoded PNG strings, one per figure
        error           (str|None)  — traceback string if execution failed
        dataframe_changed (bool)    — True if df shape or columns changed
        new_df_pickle   (bytes|None)— pickled new df if it changed, else None
    """
    import io
    import base64
    import contextlib
    import traceback
    import builtins

    import pandas as pd
    import numpy as np
    import matplotlib.pyplot as plt
    plt.switch_backend("agg")
    import seaborn as sns
    import sklearn

    safe_builtins = {
        k: v for k, v in vars(builtins).items()
        if k not in _BLOCKED_BUILTINS
    }

    df = pickle.loads(df_pickle)
    original_shape = df.shape
    original_columns = list(df.columns)

    plt.close("all")

    # Libraries come from sandbox_libraries.py — the single source of truth shared
    # with session.py and (future) llm.py. The local imports above are still needed
    # so the child process has the actual module objects.
    from sandbox_libraries import SANDBOX_NAMESPACE_LIBRARIES

    namespace = {
        **SANDBOX_NAMESPACE_LIBRARIES,
        "df": df,
        "__builtins__": safe_builtins,
    }

    result: dict = {
        "stdout": "",
        "figures": [],
        "error": None,
        "dataframe_changed": False,
        "new_df_pickle": None,
    }

    output = io.StringIO()

    # --- User code execution (errors here are the user's/LLM's fault) ---
    try:
        with contextlib.redirect_stdout(output):
            exec(code, namespace)  # noqa: S102
        result["stdout"] = output.getvalue()
    except Exception:
        result["error"] = traceback.format_exc()
        return result

    # --- Infrastructure: figure capture + df change detection ---
    # Errors here are our fault, not the user's. Surface them distinctly
    # so the user doesn't waste time debugging their code for our bug.
    try:
        for fig_num in plt.get_fignums():
            fig = plt.figure(fig_num)
            buf = io.BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight")
            buf.seek(0)
            result["figures"].append(base64.b64encode(buf.read()).decode("utf-8"))
            plt.close(fig)

        new_df = namespace.get("df", df)
        if _detect_dataframe_change(original_shape, original_columns, new_df):
            result["dataframe_changed"] = True
            if hasattr(new_df, "to_pickle"):
                result["new_df_pickle"] = pickle.dumps(new_df)
    except Exception:
        result["error"] = (
            "Internal sandbox error (not caused by your code): "
            + traceback.format_exc()
        )

    return result


def _worker_process(code: str, df_pickle: bytes, conn: "multiprocessing.connection.Connection") -> None:
    """
    Entry point for the child process spawned by execute_code().

    Runs _execute_in_sandbox and sends the result dict back through the Pipe.
    If _execute_in_sandbox itself raises (unexpected), sends an error dict.
    Must be a top-level function so multiprocessing can import it.
    """
    import traceback
    try:
        result = _execute_in_sandbox(code, df_pickle)
        conn.send(result)
    except Exception:
        conn.send({"stdout": "", "figures": [], "error": traceback.format_exc(),
                    "dataframe_changed": False, "new_df_pickle": None})
    finally:
        conn.close()


def execute_code(
    code: str,
    namespace: dict,
    timeout: int = DEFAULT_EXECUTION_TIMEOUT_SECONDS,
) -> dict:
    """
    Public API: run _execute_in_sandbox in an isolated child process with a timeout.

    Extracts the DataFrame from namespace, pickles it into the child process,
    and writes the updated DataFrame back to namespace["df"] if it changed.

    Uses multiprocessing.Process so the child can be killed with process.kill()
    on timeout — no zombie threads, no GIL contention, works on all platforms.

    Failure modes:
    - Execution timeout → result["error"] = "Code execution timed out"
    - Sandbox error (import blocked, runtime error) → result["error"] = traceback
    - Child process crash → result["error"] describes the crash

    Returns dict with keys: stdout, figures, error, dataframe_changed
    (new_df_pickle is consumed internally and not exposed to callers)
    """
    df = namespace.get("df")
    df_pickle = pickle.dumps(df)

    public_result: dict = {
        "stdout": "",
        "figures": [],
        "error": None,
        "dataframe_changed": False,
    }

    parent_conn, child_conn = multiprocessing.Pipe(duplex=False)

    process = multiprocessing.Process(
        target=_worker_process,
        args=(code, df_pickle, child_conn),
        daemon=True,
    )
    process.start()
    # Close child end in parent so the pipe doesn't stay open if the child dies.
    child_conn.close()

    process.join(timeout=timeout)

    if process.is_alive():
        process.kill()
        process.join()
        public_result["error"] = "Code execution timed out"
        return public_result

    if parent_conn.poll():
        worker_result = parent_conn.recv()
        public_result["stdout"] = worker_result.get("stdout", "")
        public_result["figures"] = worker_result.get("figures", [])
        public_result["error"] = worker_result.get("error")
        public_result["dataframe_changed"] = worker_result.get("dataframe_changed", False)

        if worker_result.get("new_df_pickle") is not None:
            namespace["df"] = pickle.loads(worker_result["new_df_pickle"])
    else:
        public_result["error"] = "Code execution failed: child process exited without producing a result"

    return public_result
