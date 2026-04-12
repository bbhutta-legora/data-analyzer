# tests/test_upload.py
# Tests for the file upload endpoint.
# Related module: backend/main.py (/api/upload route)
# PRD: supports #1 (Upload) — the entry point to every other feature
#
# Confirmed behavior list (TEST-STRATEGY Steps 1–2):
#  1. Uploading a valid CSV creates a session and returns metadata (session_id, datasets dict
#     with row_count, column_count, columns, dtypes, missing_values)
#  2. Uploading a valid single-sheet Excel file creates a session and returns metadata
#  3. Uploading a multi-sheet Excel file creates a session with all sheets as separate
#     DataFrames, metadata returned per sheet
#  4. Uploading an unsupported file type returns 400 with error: "unsupported_file_type"
#  5. Uploading an empty file returns 400 with error: "empty_file"
#  6. Uploading a file exceeding 50MB returns 413 with error: "file_too_large"
#  7. Uploading a malformed/unparseable file returns 400 with error: "parse_error"
#  8. The missing_values field accurately reports per-column null counts
#
# Tests: FastAPI TestClient (synchronous, in-process) — no subprocess needed.

import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def csv_with_nulls() -> bytes:
    """3-row CSV with 1 null in 'name', 0 nulls in 'age', 1 null in 'score'."""
    df = pd.DataFrame({
        "name": ["Alice", None, "Charlie"],
        "age": [30, 25, 35],
        "score": [90.5, 85.0, None],
    })
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode()


@pytest.fixture
def single_sheet_excel() -> bytes:
    """Single-sheet .xlsx with 2 rows and columns col1, col2."""
    df = pd.DataFrame({"col1": [1, 2], "col2": [3, 4]})
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="Sheet1")
    buf.seek(0)
    return buf.read()


@pytest.fixture
def multi_sheet_excel() -> bytes:
    """Two-sheet .xlsx: 'Sales' with column 'revenue', 'Costs' with column 'amount'."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame({"revenue": [100, 200]}).to_excel(writer, sheet_name="Sales", index=False)
        pd.DataFrame({"amount": [50, 75]}).to_excel(writer, sheet_name="Costs", index=False)
    buf.seek(0)
    return buf.read()


EXCEL_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ── CSV upload ─────────────────────────────────────────────────────────────────

def test_upload_csv_returns_session_and_metadata(csv_with_nulls):
    # Behavior 1: valid CSV creates a session and returns structured metadata.
    response = client.post(
        "/api/upload",
        files={"file": ("data.csv", csv_with_nulls, "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert "session_id" in body
    assert isinstance(body["session_id"], str)
    assert "datasets" in body
    assert "data" in body["datasets"]
    dataset = body["datasets"]["data"]
    assert dataset["row_count"] == 3
    assert dataset["column_count"] == 3
    assert "name" in dataset["columns"]
    assert "age" in dataset["columns"]
    assert "score" in dataset["columns"]
    assert "dtypes" in dataset
    assert isinstance(dataset["dtypes"], dict)
    assert "missing_values" in dataset


# ── Single-sheet Excel upload ──────────────────────────────────────────────────

def test_upload_single_sheet_excel_returns_session_and_metadata(single_sheet_excel):
    # Behavior 2: single-sheet Excel creates a session with one dataset entry.
    response = client.post(
        "/api/upload",
        files={"file": ("data.xlsx", single_sheet_excel, EXCEL_CONTENT_TYPE)},
    )
    assert response.status_code == 200
    body = response.json()
    assert "session_id" in body
    assert "datasets" in body
    # Single-sheet Excel: keyed by sheet name
    assert "Sheet1" in body["datasets"]
    assert body["datasets"]["Sheet1"]["row_count"] == 2


# ── Multi-sheet Excel upload ───────────────────────────────────────────────────

def test_upload_multi_sheet_excel_returns_all_sheets(multi_sheet_excel):
    # Behavior 3: multi-sheet Excel creates a session with one dataset entry per sheet.
    response = client.post(
        "/api/upload",
        files={"file": ("data.xlsx", multi_sheet_excel, EXCEL_CONTENT_TYPE)},
    )
    assert response.status_code == 200
    body = response.json()
    assert "session_id" in body
    assert "Sales" in body["datasets"]
    assert "Costs" in body["datasets"]
    assert "revenue" in body["datasets"]["Sales"]["columns"]
    assert "amount" in body["datasets"]["Costs"]["columns"]


# ── Validation errors ──────────────────────────────────────────────────────────

def test_upload_unsupported_file_type_returns_400():
    # Behavior 4: unsupported extension returns 400 with machine-readable error type.
    response = client.post(
        "/api/upload",
        files={"file": ("data.txt", b"some content", "text/plain")},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "unsupported_file_type"
    assert "detail" in body


def test_upload_empty_file_returns_400():
    # Behavior 5: zero-byte file returns 400 with machine-readable error type.
    response = client.post(
        "/api/upload",
        files={"file": ("data.csv", b"", "text/csv")},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "empty_file"
    assert "detail" in body


def test_upload_file_too_large_returns_413():
    # Behavior 6: file exceeding 50MB returns 413 with machine-readable error type.
    # 51MB of bytes — content doesn't matter, size check happens before parsing.
    oversized = b"x" * (51 * 1024 * 1024)
    response = client.post(
        "/api/upload",
        files={"file": ("data.csv", oversized, "text/csv")},
    )
    assert response.status_code == 413
    body = response.json()
    assert body["error"] == "file_too_large"
    assert "detail" in body


# ── Parse errors ──────────────────────────────────────────────────────────────

def test_upload_malformed_csv_returns_400():
    # When a file with a .csv extension contains unparseable content,
    # the response should be 400 with error: "parse_error" rather than a 500.
    malformed = b"\x00\x01\x02\x03\xff\xfe"  # binary garbage, not valid CSV
    response = client.post(
        "/api/upload",
        files={"file": ("data.csv", malformed, "text/csv")},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "parse_error"
    assert "detail" in body


# ── Metadata accuracy ──────────────────────────────────────────────────────────

def test_upload_missing_values_are_accurate(csv_with_nulls):
    # Behavior 7: missing_values dict reflects actual per-column null counts.
    response = client.post(
        "/api/upload",
        files={"file": ("data.csv", csv_with_nulls, "text/csv")},
    )
    assert response.status_code == 200
    missing = response.json()["datasets"]["data"]["missing_values"]
    assert missing["name"] == 1
    assert missing["age"] == 0
    assert missing["score"] == 1
