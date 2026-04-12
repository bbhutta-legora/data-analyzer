# session.py
# In-memory session store: creates, retrieves, and deletes sessions.
# Supports: every PRD feature — sessions are the central state carrier across
#   upload (#1), Q&A (#3), cleaning (#4), ML (#5), and export (#7).
# Key deps: pandas (dataframe storage), uuid (unique session IDs),
#   sandbox_libraries.py (single source of truth for exec namespace libraries)
#
# Namespace model: the exec namespace exposes all DataFrames as a single dict
#   bound to "dfs". LLM-generated code references them as dfs["name"].
#   This gives the LLM one unambiguous access pattern regardless of how many
#   DataFrames the session holds.
#
# Architecture ref: "Session Management" in planning/architecture.md
# Tests: backend/tests/test_session.py

import uuid
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from sandbox_libraries import SANDBOX_NAMESPACE_LIBRARIES


@dataclass
class Session:
    """
    All mutable state for one user session.

    dataframes_original — immutable snapshots taken at upload time, keyed by name;
        used to restore state if the user resets after cleaning operations.
    dataframes — the working copies, keyed by name; mutated by cleaning actions
        and exec operations.
    exec_namespace — Python namespace injected into sandboxed code execution (executor.py).
        Pre-loaded with dfs (all DataFrames by name) and standard analysis libraries
        so LLM-generated code can reference them without importing.
    conversation_history — list of {role, content} dicts sent to the LLM on each turn.
    code_history — list of {code, explanation} dicts written into the exported notebook.
    api_key — stored per-session after BYOK validation so it doesn't need re-sending.
    """

    session_id: str
    dataframes_original: dict[str, pd.DataFrame]
    dataframes: dict[str, pd.DataFrame]
    conversation_history: list = field(default_factory=list)
    code_history: list = field(default_factory=list)
    exec_namespace: dict = field(default_factory=dict)
    api_key: str = ""
    # Provider and model are set alongside api_key when the user validates their key.
    # All three are passed to llm.py on every LLM call so the correct SDK and
    # model are used. Valid values are defined in providers.py.
    provider: str = ""
    model: str = ""

    def __post_init__(self) -> None:
        # Libraries come from sandbox_libraries.py — the single source of truth shared
        # with llm.py's system prompt. Add new libraries there, not here.
        self.exec_namespace = {
            **SANDBOX_NAMESPACE_LIBRARIES,
            "dfs": self.dataframes,
            "print": print,
        }


class SessionStore:
    """
    Thread-unsafe in-memory store for Session objects.

    Acceptable for single-process FastAPI prototype.
    REVIEW: replace with a thread-safe store if concurrency requirements grow.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, dataframes: dict[str, pd.DataFrame], api_key: str = "", provider: str = "", model: str = "") -> str:
        """
        Create a new session from a dict of named DataFrames and return its session_id.

        Each DataFrame is copied independently — both the working copy and the original —
        so external mutations after this call and mutations to one DataFrame cannot
        affect others or their originals.

        Failure modes: none — always succeeds, including for empty DataFrames.
        """
        session_id = str(uuid.uuid4())

        # Copy each DataFrame independently so working copies and originals are isolated.
        working_copies = {name: df.copy() for name, df in dataframes.items()}
        original_copies = {name: df.copy() for name, df in dataframes.items()}

        session = Session(
            session_id=session_id,
            dataframes_original=original_copies,
            dataframes=working_copies,
            api_key=api_key,
            provider=provider,
            model=model,
        )
        self._sessions[session_id] = session
        return session_id

    def get(self, session_id: str) -> Optional[Session]:
        """
        Return the Session for session_id, or None if it does not exist.

        Callers must check for None and return a 404 — never let a missing session
        propagate as an AttributeError or KeyError into a route handler.
        """
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> bool:
        """
        Remove a session from the store.

        Returns True if the session existed and was deleted.
        Returns False if session_id was not found — no exception is raised,
        but the caller should surface this to the user so they can clarify.
        """
        if session_id not in self._sessions:
            return False
        del self._sessions[session_id]
        return True
