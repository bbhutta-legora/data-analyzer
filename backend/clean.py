# clean.py
# Pure data cleaning functions: no I/O, no session state, no side effects.
# Supports: PRD #4 (Data Cleaning)
# Key deps: pandas (DataFrame operations)
#
# Design: each cleaning action is a pure function that takes a DataFrame (and
# optional column name) and returns a new DataFrame. apply_cleaning_action()
# dispatches to the correct handler. The route handler in main.py owns I/O
# (session lookup, response building) and calls these pure functions.
#
# Architecture ref: "Data Cleaning" in planning/architecture.md §3.3
# Tests: backend/tests/test_clean.py

import pandas as pd

# ── Valid actions ─────────────────────────────────────────────────────────────
# Used by the /api/clean endpoint to validate the action before dispatching.

VALID_ACTIONS = frozenset({"drop_duplicates", "fill_median", "drop_missing_rows"})


# ── Pure cleaning functions ───────────────────────────────────────────────────


def drop_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove duplicate rows from a DataFrame.

    Returns a new DataFrame with duplicate rows removed; the input is not mutated.

    Failure modes: none — always returns a valid DataFrame (empty if all rows are duplicates).
    """
    return df.drop_duplicates()


def fill_median(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """
    Fill NaN values in a numeric column with the column's median.

    Returns a new DataFrame with NaN values in the specified column replaced by the median.
    The input DataFrame is not mutated.

    Failure modes:
    - column is not in df.columns → raises KeyError (caught by route handler)
    - column is not numeric → raises ValueError
    """
    if not pd.api.types.is_numeric_dtype(df[column]):
        raise ValueError(
            "Column '" + column + "' is not numeric. "
            "fill_median only works on numeric columns."
        )
    result = df.copy()
    median_value = result[column].median()
    result[column] = result[column].fillna(median_value)
    return result


def drop_missing_rows(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """
    Drop rows where the specified column has NaN values.

    Returns a new DataFrame with rows removed where the specified column is null.
    The input DataFrame is not mutated.

    Failure modes:
    - column is not in df.columns → raises KeyError (caught by route handler)
    """
    return df.dropna(subset=[column])


# ── Dispatch ──────────────────────────────────────────────────────────────────


def apply_cleaning_action(
    df: pd.DataFrame,
    action: str,
    column: str | None = None,
) -> pd.DataFrame:
    """
    Dispatch a cleaning action to the correct handler function.

    Returns a new DataFrame with the cleaning action applied.
    The input DataFrame is not mutated.

    Failure modes:
    - Unknown action → raises ValueError
    - Action requires column but column is None → raises TypeError from handler
    - Handler-specific failures (non-numeric column, missing column) → propagate
    """
    if action not in VALID_ACTIONS:
        raise ValueError(
            "Unknown cleaning action: '" + action + "'. "
            "Valid actions: " + ", ".join(sorted(VALID_ACTIONS))
        )

    if action == "drop_duplicates":
        return drop_duplicates(df)
    if action == "fill_median":
        return fill_median(df, column)
    # action == "drop_missing_rows"
    return drop_missing_rows(df, column)
