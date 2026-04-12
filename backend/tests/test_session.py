# tests/test_session.py
# Tests for session lifecycle management.
# Related module: backend/session.py
# PRD: session state underpins every feature — upload (#1), Q&A (#3), cleaning (#4), ML (#5), export (#7)
#
# Confirmed behavior list (TEST-STRATEGY Step 1):
#  1. Create returns unique string IDs
#  2. Get by ID returns stored session with correct DataFrames
#  3. Get non-existent ID returns None
#  4. Delete existing session returns True and makes it unretrievable
#  5. Delete non-existent ID returns False silently
#  6. Session starts with empty conversation and code history
#  7. exec_namespace contains dfs bound to the session's DataFrames dict
#  8. External mutation after create does not affect session's DataFrames
#  9. Mutating a working copy does not affect the original
# 10. exec_namespace pre-loads pd, np, plt, sns, sklearn
# 11. Creating a session with an empty DataFrame succeeds
# 12. api_key is stored and retrievable on the session
# 13. Creating a session with multiple DataFrames stores all of them by name
# 14. Each DataFrame in the dict is independently copied — mutating one doesn't affect others

import pandas as pd
from session import SessionStore


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_store() -> SessionStore:
    """Return a fresh, empty SessionStore for each test."""
    return SessionStore()


def small_df() -> pd.DataFrame:
    return pd.DataFrame({"a": [1, 2, 3]})


def make_dfs() -> dict[str, pd.DataFrame]:
    """Single-DataFrame dict — the common case (e.g. CSV upload)."""
    return {"data": small_df()}


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_create_returns_unique_string_ids():
    # Behavior 1: unique IDs across multiple creates.
    # Why: colliding IDs merge two users' sessions, corrupting their data.
    store = make_store()
    id1 = store.create(make_dfs())
    id2 = store.create(make_dfs())
    assert isinstance(id1, str)
    assert isinstance(id2, str)
    assert id1 != id2


def test_get_by_id_returns_stored_session():
    # Behavior 2: retrieval by ID returns the correct session.
    # Why: every chat message and export depends on fetching the right session.
    store = make_store()
    df = small_df()
    session_id = store.create({"data": df})
    session = store.get(session_id)
    assert session is not None
    assert session.dataframes["data"].equals(df)


def test_get_nonexistent_id_returns_none():
    # Behavior 3: missing session ID returns None, not an exception.
    # Why: route handlers check for None to return 404; an exception would crash the server.
    store = make_store()
    result = store.get("nonexistent-id")
    assert result is None


def test_delete_existing_session_returns_true_and_removes_it():
    # Behavior 4: deleting a session returns True and makes it unretrievable.
    # Why: confirms the delete path works so future cleanup logic can rely on it.
    store = make_store()
    session_id = store.create(make_dfs())
    deleted = store.delete(session_id)
    assert deleted is True
    assert store.get(session_id) is None


def test_delete_nonexistent_id_returns_false():
    # Behavior 5: deleting a missing ID returns False without raising.
    # Why: cleanup code can call delete defensively; False tells the caller the ID wasn't found
    #      so it can inform the user, without crashing.
    store = make_store()
    result = store.delete("nonexistent-id")
    assert result is False


def test_session_starts_with_empty_conversation_and_code_history():
    # Behavior 6: both history lists are empty on creation.
    # Why: if history isn't empty, the LLM receives phantom prior messages on the first turn,
    #      producing a confusing or incorrect response.
    store = make_store()
    session = store.get(store.create(make_dfs()))
    assert session.conversation_history == []
    assert session.code_history == []


def test_exec_namespace_contains_dfs():
    # Behavior 7: exec_namespace has 'dfs' bound to the session's DataFrames dict.
    # Why: LLM-generated code always references dfs["name"]; a missing binding means every
    #      code execution fails with NameError.
    store = make_store()
    df = pd.DataFrame({"x": [10, 20]})
    session = store.get(store.create({"data": df}))
    assert "dfs" in session.exec_namespace
    assert session.exec_namespace["dfs"]["data"].equals(df)


def test_external_mutation_after_create_does_not_affect_session():
    # Behavior 8: the session copies each DataFrame on creation.
    # Why: if the caller mutates their reference after creating the session, the session
    #      should not silently reflect that — it would corrupt the working copy mid-analysis.
    store = make_store()
    df = small_df()
    session = store.get(store.create({"data": df}))
    df.drop(columns=["a"], inplace=True)
    assert "a" in session.dataframes["data"].columns


def test_mutating_working_copy_does_not_affect_original():
    # Behavior 9: dataframes_original is immune to changes on dataframes.
    # Why: data cleaning is destructive; if the original isn't protected, "reset to original"
    #      is impossible without re-uploading the file.
    store = make_store()
    session = store.get(store.create(make_dfs()))
    session.dataframes["data"] = session.dataframes["data"].drop(columns=["a"])
    assert "a" in session.dataframes_original["data"].columns


def test_exec_namespace_preloads_standard_libraries():
    # Behavior 10: pd, np, plt, sns, sklearn are pre-bound in the exec namespace.
    # Why: LLM-generated code uses these without importing them. A missing binding means
    #      every code execution fails with NameError, breaking the entire Q&A feature.
    store = make_store()
    session = store.get(store.create(make_dfs()))
    ns = session.exec_namespace
    for lib_name in ("pd", "np", "plt", "sns", "sklearn"):
        assert lib_name in ns, f"Expected '{lib_name}' in exec_namespace but it was missing"


def test_create_with_empty_dataframe_succeeds():
    # Behavior 11: an empty dataframe (0 rows) creates a valid session without raising.
    # Why: a user may upload a headers-only CSV. A crash here produces a 500 instead of a
    #      clean message telling the user their file has no data.
    store = make_store()
    empty_df = pd.DataFrame({"col1": [], "col2": []})
    session_id = store.create({"data": empty_df})
    assert store.get(session_id) is not None


def test_api_key_is_stored_and_retrievable():
    # Behavior 12: the api_key passed at creation is accessible on the session.
    # Why: the BYOK key is stored per-session so it doesn't have to be re-sent on every
    #      chat message. If it isn't stored, every LLM call fails with an auth error.
    store = make_store()
    session_id = store.create(make_dfs(), api_key="sk-test-key")
    session = store.get(session_id)
    assert session.api_key == "sk-test-key"


def test_create_with_multiple_dataframes_stores_all_by_name():
    # Behavior 13: a session created with multiple DataFrames retains all of them.
    # Why: multi-sheet Excel uploads need every sheet retrievable by name;
    #      a missing sheet means the user loses data silently.
    store = make_store()
    df_sales = pd.DataFrame({"revenue": [100, 200]})
    df_costs = pd.DataFrame({"amount": [50, 75]})
    session = store.get(store.create({"sales": df_sales, "costs": df_costs}))
    assert "sales" in session.dataframes
    assert "costs" in session.dataframes
    assert session.dataframes["sales"].equals(df_sales)
    assert session.dataframes["costs"].equals(df_costs)


def test_mutating_one_dataframe_does_not_affect_others():
    # Behavior 14: each DataFrame in the dict is independently copied.
    # Why: cleaning "sales" should never silently corrupt "costs" or either original.
    store = make_store()
    df_sales = pd.DataFrame({"revenue": [100]})
    df_costs = pd.DataFrame({"amount": [50]})
    session = store.get(store.create({"sales": df_sales, "costs": df_costs}))
    session.dataframes["sales"] = session.dataframes["sales"].drop(columns=["revenue"])
    assert "amount" in session.dataframes["costs"].columns
    assert "revenue" in session.dataframes_original["sales"].columns
    assert "amount" in session.dataframes_original["costs"].columns
