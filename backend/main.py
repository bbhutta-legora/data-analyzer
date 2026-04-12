# main.py
# Entry point for the Smart Dataset Explainer backend API.
# Supports: PRD #1 (upload), #2 (summary), #3 (Q&A), #4 (cleaning), #5 (ML), #7 (export), #8 (BYOK)
# Key deps: FastAPI (routing), session.py (in-memory state), executor.py (sandboxed code runs)
#
# Routes are added incrementally per the implementation plan:
#   Step 4:  /api/upload   — file upload + session creation
#   Step 6:  /api/validate-key — BYOK key validation
#            /api/models        — curated model list per provider
#   Step 7:  /api/upload (modified) — adds LLM summary call
#   Step 8:  /api/chat     — SSE streaming Q&A
#   Step 10: /api/clean    — data cleaning actions
#   Step 14: /api/export   — notebook export

import io
import logging
import pathlib

import pandas as pd
from fastapi import FastAPI, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from llm import generate_summary
from providers import ANTHROPIC_VALIDATION_MODEL, AVAILABLE_MODELS, ProviderLiteral
from session import SessionStore

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

FRONTEND_DEV_ORIGIN = "http://localhost:5173"

# Extensions must be lowercase — filenames are normalised before comparison.
ALLOWED_UPLOAD_EXTENSIONS = (".csv", ".xlsx", ".xls")

MAX_UPLOAD_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="Smart Dataset Explainer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_DEV_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single shared session store for the lifetime of the process.
# Sessions are created on upload and discarded on server restart (no persistence).
session_store = SessionStore()


# ── Pure helpers ───────────────────────────────────────────────────────────────

def parse_dataframes_from_bytes(content: bytes, filename: str) -> dict[str, pd.DataFrame]:
    """
    Parse uploaded file bytes into a dict of named DataFrames.

    CSV files produce a single entry keyed by the filename stem (e.g. "sales" for "sales.csv").
    Excel files produce one entry per sheet keyed by sheet name.

    Failure modes:
    - pandas.errors.ParserError if the CSV is malformed → propagates to caller
    - Corrupt Excel file → propagates to caller
    """
    extension = pathlib.Path(filename).suffix.lower()
    stem = pathlib.Path(filename).stem

    if extension == ".csv":
        df = pd.read_csv(io.BytesIO(content))
        return {stem: df}

    # Excel: read all sheets into a dict[sheet_name, DataFrame].
    # sheet_name=None tells pandas to return every sheet.
    sheets: dict[str, pd.DataFrame] = pd.read_excel(
        io.BytesIO(content),
        sheet_name=None,
        engine="openpyxl",
    )
    return sheets


def build_dataset_metadata(dataframes: dict[str, pd.DataFrame]) -> dict[str, dict]:
    """
    Build a per-DataFrame metadata dict from a session's DataFrames.

    Returns a dict keyed by DataFrame name, each value containing:
        row_count     (int)         — number of rows
        column_count  (int)         — number of columns
        columns       (list[str])   — column names in order
        dtypes        (dict[str, str]) — column name → pandas dtype string
        missing_values (dict[str, int]) — column name → null count

    Failure modes: none — always succeeds for valid DataFrames.
    """
    metadata: dict[str, dict] = {}

    for name, df in dataframes.items():
        metadata[name] = {
            "row_count": len(df),
            "column_count": len(df.columns),
            "columns": list(df.columns),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "missing_values": {col: int(df[col].isnull().sum()) for col in df.columns},
        }

    return metadata


# ── Key validation helpers ────────────────────────────────────────────────────

def validate_openai_key(api_key: str) -> bool:
    """
    Check whether api_key is a working OpenAI key by listing available models.

    Uses max_retries=0 so an invalid key fails fast rather than retrying.
    Returns True if the key is accepted, False if the API returns an auth error.

    Failure modes:
    - openai.AuthenticationError → returns False (invalid key)
    - Any other exception (network, timeout) → propagates to caller;
      the route handler catches it and returns 500.
    """
    # Imported here rather than at module level so only the provider the user
    # selects pays the SDK import cost — both SDKs are large and slow to import.
    import openai
    try:
        openai.OpenAI(api_key=api_key, max_retries=0).models.list()
        return True
    except openai.AuthenticationError:
        return False


def validate_anthropic_key(api_key: str) -> bool:
    """
    Check whether api_key is a working Anthropic key by sending a minimal message.

    max_tokens=1 keeps the check cheap — we only care about auth, not content.
    Returns True if the key is accepted, False if the API returns an auth error.

    Failure modes:
    - anthropic.AuthenticationError → returns False (invalid key)
    - Any other exception (network, timeout) → propagates to caller;
      the route handler catches it and returns 500.
    """
    # Imported here rather than at module level so only the provider the user
    # selects pays the SDK import cost — both SDKs are large and slow to import.
    import anthropic
    try:
        anthropic.Anthropic(api_key=api_key, max_retries=0).messages.create(
            model=ANTHROPIC_VALIDATION_MODEL,
            max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )
        return True
    except anthropic.AuthenticationError:
        return False


# ── Request / response models ─────────────────────────────────────────────────

class ValidateKeyRequest(BaseModel):
    api_key: str
    provider: ProviderLiteral


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/models")
def get_available_models() -> JSONResponse:
    """
    Return the curated list of available models per provider.

    The frontend calls this on the setup screen to populate the model dropdown.
    Models are defined in providers.py — this endpoint is the bridge so the
    frontend doesn't need to duplicate the list.
    """
    serialized = {
        provider: [model.to_dict() for model in models]
        for provider, models in AVAILABLE_MODELS.items()
    }
    return JSONResponse(status_code=200, content=serialized)


@app.post("/api/validate-key")
def validate_key(body: ValidateKeyRequest) -> JSONResponse:
    """
    Validate a provider API key by making a lightweight API call.

    Strip whitespace from the key first so copy-paste artifacts don't cause
    false rejections. Return 400 for an empty key (after stripping) so the
    frontend can show a clear "enter your key" message rather than a provider
    auth error.

    PRD ref: #8 (BYOK) — key is validated here and stored in the session at
    upload time (Step 7). Not stored server-side until a session is created.

    Architecture ref: "BYOK" in planning/architecture.md
    """
    api_key = body.api_key.strip()

    if not api_key:
        return JSONResponse(
            status_code=400,
            content={
                "error": "empty_api_key",
                "detail": "API key cannot be empty. Enter your key and try again.",
            },
        )

    is_valid = (
        validate_openai_key(api_key)
        if body.provider == "openai"
        else validate_anthropic_key(api_key)
    )

    if not is_valid:
        return JSONResponse(
            status_code=401,
            content={
                "valid": False,
                "error": "invalid_api_key",
                "detail": (
                    f"The {body.provider} API key was rejected. "
                    "Check that the key is correct and has not been revoked."
                ),
            },
        )

    return JSONResponse(status_code=200, content={"valid": True})


@app.post("/api/upload")
def upload_file(
    file: UploadFile,
    api_key: str = Form(""),
    provider: str = Form(""),
    model: str = Form(""),
) -> JSONResponse:
    """
    Accept a CSV or Excel file, parse it into DataFrames, create a session,
    and return dataset metadata. When credentials are provided, also calls the
    LLM to generate an initial dataset summary (PRD #2).

    The api_key/provider/model Form fields are optional — omitting them skips
    the LLM call and returns only structural metadata. This preserves backward
    compatibility with existing upload tests and allows file parsing to work
    independently of LLM availability.

    Uses a sync def (not async) because all work is synchronous pandas I/O
    and the LLM SDK calls are also synchronous.
    FastAPI runs sync handlers in a threadpool automatically.

    Architecture ref: "File upload (REST)" in planning/architecture.md §3.3
    """
    filename = file.filename or ""
    extension = pathlib.Path(filename).suffix.lower()

    # Guard: unsupported file type
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        return JSONResponse(
            status_code=400,
            content={
                "error": "unsupported_file_type",
                "detail": (
                    f"File '{filename}' has extension '{extension}'. "
                    f"Supported formats: {', '.join(ALLOWED_UPLOAD_EXTENSIONS)}"
                ),
            },
        )

    content = file.file.read()

    # Guard: empty file
    if len(content) == 0:
        return JSONResponse(
            status_code=400,
            content={
                "error": "empty_file",
                "detail": f"File '{filename}' is empty. Upload a file with at least one row of data.",
            },
        )

    # Guard: file too large
    if len(content) > MAX_UPLOAD_FILE_SIZE_BYTES:
        limit_mb = MAX_UPLOAD_FILE_SIZE_BYTES // (1024 * 1024)
        return JSONResponse(
            status_code=413,
            content={
                "error": "file_too_large",
                "detail": f"File '{filename}' exceeds the {limit_mb}MB upload limit.",
            },
        )

    try:
        dataframes = parse_dataframes_from_bytes(content, filename)
    except Exception as exc:
        # Broad catch is intentional — malformed CSV, corrupt Excel, or unsupported
        # encoding all surface as different pandas/openpyxl exceptions. We catch
        # them here with a clear message rather than letting FastAPI produce a 500
        # with a raw traceback.
        return JSONResponse(
            status_code=400,
            content={
                "error": "parse_error",
                "detail": f"Could not parse '{filename}': {exc}",
            },
        )

    session_id = session_store.create(
        dataframes, api_key=api_key, provider=provider, model=model,
    )
    datasets = build_dataset_metadata(dataframes)

    response_content: dict = {
        "session_id": session_id,
        "datasets": datasets,
    }

    # Only call the LLM if credentials were provided.
    # Without credentials, the upload still works for parsing/metadata.
    if api_key and provider and model:
        logger.info("Generating LLM summary for session %s", session_id)
        summary = generate_summary(dataframes, api_key, provider, model)
        response_content["summary"] = summary

    return JSONResponse(status_code=200, content=response_content)
