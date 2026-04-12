# tests/test_clean.py
# Tests for the data cleaning endpoint and pure cleaning functions.
# Related modules: backend/clean.py, backend/main.py (/api/clean route)
# PRD: #4 (Data Cleaning)
#
# Confirmed behavior list (TEST-STRATEGY Steps 1-2):
#
# Pure cleaning functions (backend/clean.py):
#  1. drop_duplicates removes duplicate rows and returns a new DataFrame
#  2. fill_median fills NaN values in a numeric column with the column median
#  3. fill_median raises ValueError for non-numeric column
#  4. drop_missing_rows drops rows with NaN in a specified column
#  5. apply_cleaning_action dispatches to the correct handler
#  6. apply_cleaning_action raises ValueError for unknown action
#  7. VALID_ACTIONS contains exactly the supported action names
#  8. Pure functions do not mutate the input DataFrame
#
# /api/clean endpoint:
#  9. Valid cleaning action returns 200 with updated metadata
# 10. Response contains row_count, column_count, columns, dtypes, missing_values
# 11. Cleaning action modifies the session's working DataFrame
# 12. Cleaning action does NOT modify the session's original DataFrame
# 13. Unknown session_id returns 404
# 14. Invalid action returns 400
# 15. fill_median with missing column returns 400
# 16. Dataset name resolves to correct DataFrame in multi-DF session
# 17. Missing dataset_name defaults to the first DataFrame
#
# /api/clean/reset endpoint:
# 18. Reset restores working DataFrames from originals
# 19. Reset returns updated metadata reflecting original data
# 20. Reset for unknown session returns 404

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from clean import (
    VALID_ACTIONS,
    apply_cleaning_action,
    drop_duplicates,
    drop_missing_rows,
    fill_median,
)
from main import app, session_store

client = TestClient(app)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def df_with_duplicates() -> pd.DataFrame:
    """DataFrame with 2 duplicate rows out of 4."""
    return pd.DataFrame({
        "name": ["Alice", "Bob", "Alice", "Bob"],
        "age": [30, 25, 30, 25],
    })


@pytest.fixture
def df_with_nulls() -> pd.DataFrame:
    """DataFrame with NaN values in numeric and string columns."""
    return pd.DataFrame({
        "name": ["Alice", None, "Charlie"],
        "score": [90.0, None, 70.0],
        "grade": ["A", "B", None],
    })


# ── Helpers ───────────────────────────────────────────────────────────────────


def create_session_with_data(
    dataframes: dict[str, pd.DataFrame] | None = None,
) -> str:
    """Create a session in the shared store and return its session_id."""
    if dataframes is None:
        dataframes = {
            "data": pd.DataFrame({
                "name": ["Alice", None, "Charlie"],
                "score": [90.0, None, 70.0],
            }),
        }
    return session_store.create(dataframes, api_key="sk-test", provider="openai", model="gpt-4")


# ── Pure function tests: drop_duplicates ──────────────────────────────────────


def test_drop_duplicates_removes_duplicate_rows(df_with_duplicates):
    # Behavior 1: duplicate rows are removed, unique rows are kept.
    result = drop_duplicates(df_with_duplicates)
    assert len(result) == 2
    assert list(result["name"]) == ["Alice", "Bob"]


def test_drop_duplicates_does_not_mutate_input(df_with_duplicates):
    # Behavior 8: input DataFrame is not modified.
    original_len = len(df_with_duplicates)
    drop_duplicates(df_with_duplicates)
    assert len(df_with_duplicates) == original_len


# ── Pure function tests: fill_median ──────────────────────────────────────────


def test_fill_median_fills_nan_with_median(df_with_nulls):
    # Behavior 2: NaN values in a numeric column are replaced with the column median.
    result = fill_median(df_with_nulls, "score")
    assert result["score"].isnull().sum() == 0
    # Median of [90.0, 70.0] = 80.0
    assert result["score"].iloc[1] == 80.0


def test_fill_median_raises_for_non_numeric_column(df_with_nulls):
    # Behavior 3: non-numeric column raises ValueError.
    with pytest.raises(ValueError, match="not numeric"):
        fill_median(df_with_nulls, "name")


def test_fill_median_does_not_mutate_input(df_with_nulls):
    # Behavior 8: input DataFrame is not modified.
    original_null_count = df_with_nulls["score"].isnull().sum()
    fill_median(df_with_nulls, "score")
    assert df_with_nulls["score"].isnull().sum() == original_null_count


# ── Pure function tests: drop_missing_rows ────────────────────────────────────


def test_drop_missing_rows_removes_rows_with_nan(df_with_nulls):
    # Behavior 4: rows with NaN in the specified column are removed.
    result = drop_missing_rows(df_with_nulls, "score")
    assert len(result) == 2
    assert result["score"].isnull().sum() == 0


def test_drop_missing_rows_does_not_mutate_input(df_with_nulls):
    # Behavior 8: input DataFrame is not modified.
    original_len = len(df_with_nulls)
    drop_missing_rows(df_with_nulls, "score")
    assert len(df_with_nulls) == original_len


# ── Pure function tests: apply_cleaning_action ────────────────────────────────


def test_apply_cleaning_action_dispatches_drop_duplicates(df_with_duplicates):
    # Behavior 5: action "drop_duplicates" dispatches correctly.
    result = apply_cleaning_action(df_with_duplicates, "drop_duplicates")
    assert len(result) == 2


def test_apply_cleaning_action_dispatches_fill_median(df_with_nulls):
    # Behavior 5: action "fill_median" dispatches correctly.
    result = apply_cleaning_action(df_with_nulls, "fill_median", column="score")
    assert result["score"].isnull().sum() == 0


def test_apply_cleaning_action_dispatches_drop_missing_rows(df_with_nulls):
    # Behavior 5: action "drop_missing_rows" dispatches correctly.
    result = apply_cleaning_action(df_with_nulls, "drop_missing_rows", column="score")
    assert len(result) == 2


def test_apply_cleaning_action_raises_for_unknown_action(df_with_nulls):
    # Behavior 6: unknown action name raises ValueError.
    with pytest.raises(ValueError, match="Unknown cleaning action"):
        apply_cleaning_action(df_with_nulls, "nonexistent_action")


def test_valid_actions_contains_expected_actions():
    # Behavior 7: VALID_ACTIONS has exactly the supported action names.
    assert "drop_duplicates" in VALID_ACTIONS
    assert "fill_median" in VALID_ACTIONS
    assert "drop_missing_rows" in VALID_ACTIONS


# ── Endpoint tests: /api/clean (happy path) ──────────────────────────────────


def test_clean_endpoint_returns_updated_metadata():
    # Behavior 9+10: valid action returns 200 with updated metadata fields.
    session_id = create_session_with_data()
    response = client.post("/api/clean", json={
        "session_id": session_id,
        "action": "drop_missing_rows",
        "column": "score",
        "dataset_name": "data",
    })
    assert response.status_code == 200
    body = response.json()
    assert "row_count" in body
    assert "column_count" in body
    assert "columns" in body
    assert "dtypes" in body
    assert "missing_values" in body
    assert "message" in body
    # Original had 3 rows, 1 with null score → 2 rows remain
    assert body["row_count"] == 2


def test_clean_endpoint_modifies_working_dataframe():
    # Behavior 11: cleaning modifies the session's working DataFrame.
    session_id = create_session_with_data()
    client.post("/api/clean", json={
        "session_id": session_id,
        "action": "drop_missing_rows",
        "column": "score",
        "dataset_name": "data",
    })
    session = session_store.get(session_id)
    assert len(session.dataframes["data"]) == 2


def test_clean_endpoint_preserves_original_dataframe():
    # Behavior 12: cleaning does NOT modify the session's original DataFrame.
    session_id = create_session_with_data()
    client.post("/api/clean", json={
        "session_id": session_id,
        "action": "drop_missing_rows",
        "column": "score",
        "dataset_name": "data",
    })
    session = session_store.get(session_id)
    assert len(session.dataframes_original["data"]) == 3


# ── Endpoint tests: /api/clean (error handling) ──────────────────────────────


def test_clean_endpoint_returns_404_for_unknown_session():
    # Behavior 13: unknown session_id returns 404.
    response = client.post("/api/clean", json={
        "session_id": "nonexistent-session",
        "action": "drop_duplicates",
    })
    assert response.status_code == 404


def test_clean_endpoint_returns_400_for_invalid_action():
    # Behavior 14: invalid action returns 400.
    session_id = create_session_with_data()
    response = client.post("/api/clean", json={
        "session_id": session_id,
        "action": "totally_invalid_action",
        "dataset_name": "data",
    })
    assert response.status_code == 400
    assert "Unknown cleaning action" in response.json()["detail"]


def test_clean_endpoint_returns_400_for_missing_column():
    # Behavior 15: fill_median without a valid column returns 400.
    session_id = create_session_with_data()
    response = client.post("/api/clean", json={
        "session_id": session_id,
        "action": "fill_median",
        "column": "nonexistent_column",
        "dataset_name": "data",
    })
    assert response.status_code == 400


# ── Endpoint tests: multi-DataFrame targeting ─────────────────────────────────


def test_clean_endpoint_targets_correct_dataframe_in_multi_df_session():
    # Behavior 16: dataset_name resolves to the correct DataFrame.
    dataframes = {
        "sales": pd.DataFrame({"revenue": [100, 100, 200], "cost": [50, 50, 75]}),
        "costs": pd.DataFrame({"amount": [10, 20, 30]}),
    }
    session_id = create_session_with_data(dataframes)
    response = client.post("/api/clean", json={
        "session_id": session_id,
        "action": "drop_duplicates",
        "dataset_name": "sales",
    })
    assert response.status_code == 200
    body = response.json()
    # sales had 3 rows, 2 duplicates → 2 unique rows
    assert body["row_count"] == 2

    # costs should be untouched
    session = session_store.get(session_id)
    assert len(session.dataframes["costs"]) == 3


def test_clean_endpoint_defaults_dataset_name_to_first():
    # Behavior 17: omitting dataset_name uses the first DataFrame.
    session_id = create_session_with_data()
    response = client.post("/api/clean", json={
        "session_id": session_id,
        "action": "drop_missing_rows",
        "column": "score",
    })
    assert response.status_code == 200
    assert response.json()["row_count"] == 2


# ── Endpoint tests: /api/clean/reset ─────────────────────────────────────────


def test_reset_endpoint_restores_original_dataframes():
    # Behavior 18: reset restores working DataFrames from originals.
    session_id = create_session_with_data()

    # First, apply a cleaning action
    client.post("/api/clean", json={
        "session_id": session_id,
        "action": "drop_missing_rows",
        "column": "score",
        "dataset_name": "data",
    })
    session = session_store.get(session_id)
    assert len(session.dataframes["data"]) == 2

    # Now reset
    response = client.post("/api/clean/reset", json={
        "session_id": session_id,
    })
    assert response.status_code == 200

    session = session_store.get(session_id)
    assert len(session.dataframes["data"]) == 3


def test_reset_endpoint_returns_updated_metadata():
    # Behavior 19: reset returns metadata reflecting original data.
    session_id = create_session_with_data()

    # Clean, then reset
    client.post("/api/clean", json={
        "session_id": session_id,
        "action": "drop_missing_rows",
        "column": "score",
        "dataset_name": "data",
    })
    response = client.post("/api/clean/reset", json={
        "session_id": session_id,
    })
    assert response.status_code == 200
    body = response.json()
    assert "datasets" in body
    assert body["datasets"]["data"]["row_count"] == 3


def test_reset_endpoint_returns_404_for_unknown_session():
    # Behavior 20: unknown session returns 404.
    response = client.post("/api/clean/reset", json={
        "session_id": "nonexistent-session",
    })
    assert response.status_code == 404


# ── Edge case tests ──────────────────────────────────────────────────────────


def test_fill_median_on_all_nan_column():
    # Edge case: fill_median on a column that is ALL NaN should not crash.
    # The median of an all-NaN column is NaN, so filling with NaN is a no-op.
    df = pd.DataFrame({"val": [float("nan"), float("nan"), float("nan")]})
    result = fill_median(df, "val")
    assert len(result) == 3
    assert result["val"].isnull().all()


def test_cleaning_functions_on_empty_dataframe():
    # Edge case: cleaning functions on a DataFrame with zero rows should not crash.
    df = pd.DataFrame({"name": pd.Series([], dtype="object"), "score": pd.Series([], dtype="float64")})
    assert len(df) == 0

    result_dedup = drop_duplicates(df)
    assert len(result_dedup) == 0

    result_fill = fill_median(df, "score")
    assert len(result_fill) == 0

    result_drop = drop_missing_rows(df, "score")
    assert len(result_drop) == 0


def test_clean_endpoint_returns_400_for_column_none_with_column_requiring_action():
    # Edge case: /api/clean with a column-requiring action (fill_median) and
    # column=None should return 400, not 500.
    session_id = create_session_with_data()
    response = client.post("/api/clean", json={
        "session_id": session_id,
        "action": "fill_median",
        "column": None,
        "dataset_name": "data",
    })
    assert response.status_code == 400


def test_clean_endpoint_returns_400_for_nonexistent_dataset_name():
    # Edge case: /api/clean with a dataset_name that doesn't exist in the session
    # should return 400.
    session_id = create_session_with_data()
    response = client.post("/api/clean", json={
        "session_id": session_id,
        "action": "drop_duplicates",
        "dataset_name": "nonexistent_dataset",
    })
    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()


def test_two_chained_cleaning_actions():
    # Edge case: second action operates on the already-cleaned DataFrame.
    # Create data with duplicates AND missing values.
    dataframes = {
        "data": pd.DataFrame({
            "name": ["Alice", "Bob", "Alice", "Bob", None],
            "score": [90.0, 80.0, 90.0, 80.0, 70.0],
        }),
    }
    session_id = create_session_with_data(dataframes)

    # Step 1: drop_missing_rows on "name" — removes the row with None name.
    response1 = client.post("/api/clean", json={
        "session_id": session_id,
        "action": "drop_missing_rows",
        "column": "name",
        "dataset_name": "data",
    })
    assert response1.status_code == 200
    assert response1.json()["row_count"] == 4  # 5 - 1 missing = 4

    # Step 2: drop_duplicates — removes 2 duplicate rows from the 4 remaining.
    response2 = client.post("/api/clean", json={
        "session_id": session_id,
        "action": "drop_duplicates",
        "dataset_name": "data",
    })
    assert response2.status_code == 200
    assert response2.json()["row_count"] == 2  # 4 - 2 duplicates = 2

    # Verify the session's working DataFrame reflects both actions.
    session = session_store.get(session_id)
    assert len(session.dataframes["data"]) == 2
    # Original should still have all 5 rows.
    assert len(session.dataframes_original["data"]) == 5


def test_clean_endpoint_returns_400_for_fill_median_on_string_column():
    # Edge case: endpoint test that fill_median targeting a string column
    # returns 400 (not 500). The pure function raises ValueError which the
    # route handler catches and converts to a 400 response.
    dataframes = {
        "data": pd.DataFrame({
            "name": ["Alice", "Bob", None],
            "score": [90.0, 80.0, 70.0],
        }),
    }
    session_id = create_session_with_data(dataframes)
    response = client.post("/api/clean", json={
        "session_id": session_id,
        "action": "fill_median",
        "column": "name",
        "dataset_name": "data",
    })
    assert response.status_code == 400
    assert "not numeric" in response.json()["detail"]
