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
import json
import logging
import pathlib

import pandas as pd
from fastapi import FastAPI, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from executor import execute_code
from llm import (
    ML_STAGES,
    build_chat_messages,
    build_chat_system_prompt,
    build_explanation_prompt,
    build_feature_selection_prompt,
    build_model_selection_prompt,
    build_preprocessing_prompt,
    build_target_selection_prompt,
    build_training_prompt,
    call_llm_chat,
    generate_summary,
    infer_problem_type,
    parse_chat_response,
    parse_ml_step_response,
    truncate_history,
)
from providers import ANTHROPIC_VALIDATION_MODEL, AVAILABLE_MODELS, ProviderLiteral
from session import SessionStore

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

FRONTEND_DEV_ORIGIN = "http://localhost:5173"

# Extensions must be lowercase — filenames are normalised before comparison.
ALLOWED_UPLOAD_EXTENSIONS = (".csv", ".xlsx", ".xls")

MAX_UPLOAD_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

# Token budget for conversation history truncation. 8000 tokens leaves ~4000
# tokens of headroom for the system prompt + LLM response within a typical
# 16k-token context window.
CONVERSATION_HISTORY_MAX_TOKENS = 8000

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


class ChatRequest(BaseModel):
    session_id: str
    question: str


class MlStepRequest(BaseModel):
    session_id: str
    stage: str
    user_input: str


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


# ── Chat endpoint (Step 8) ───────────────────────────────────────────────────


@app.post("/api/chat")
def chat(request: ChatRequest):
    """
    SSE-streaming Q&A endpoint. Takes a user question and session ID, builds a
    prompt with dataset context and conversation history, calls the LLM, executes
    the generated code, and streams back explanation + execution results.

    SSE event types:
      explanation          — LLM's explanation text
      result               — execution output (stdout, figures) as JSON
      cleaning_suggestions — array of data quality suggestions as JSON
      error                — error message if LLM parse or code execution fails
      done                 — signals end of stream

    PRD ref: #3 (Conversational Q&A)
    Architecture ref: "Chat question (SSE)" in planning/architecture.md §3.3
    Tests: backend/tests/test_chat.py
    """
    session = session_store.get(request.session_id)
    if session is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "session_not_found",
                "detail": "Session not found or has expired.",
            },
        )

    if not request.question.strip():
        return JSONResponse(
            status_code=400,
            content={
                "error": "empty_question",
                "detail": "Question cannot be empty.",
            },
        )

    def event_generator():
        system_prompt = build_chat_system_prompt(session.dataframes)
        truncated = truncate_history(
            session.conversation_history, max_tokens=CONVERSATION_HISTORY_MAX_TOKENS,
        )
        messages = build_chat_messages(request.question, truncated)

        logger.info(
            "Chat request: session=%s question_length=%d history_messages=%d",
            request.session_id, len(request.question), len(truncated),
        )

        try:
            raw_response = call_llm_chat(
                system_prompt, messages, session.api_key, session.provider, session.model,
            )
        except Exception as exc:
            logger.error("LLM call failed during chat: %s", exc)
            yield _sse_event("error", "LLM call failed: " + str(exc))
            yield _sse_event("done", "")
            return

        parsed = parse_chat_response(raw_response)

        if "error" in parsed:
            yield _sse_event("error", parsed["error"])
            yield _sse_event("done", "")
            return

        yield _sse_event("explanation", parsed["explanation"])

        exec_result: dict | None = None
        if parsed.get("code"):
            exec_result = execute_code(parsed["code"], session.exec_namespace)

            if exec_result["error"]:
                yield _sse_event("error", exec_result["error"])
            else:
                result_payload = json.dumps({
                    "stdout": exec_result["stdout"],
                    "figures": exec_result["figures"],
                })
                yield _sse_event("result", result_payload)

        if parsed.get("cleaning_suggestions"):
            yield _sse_event(
                "cleaning_suggestions",
                json.dumps(parsed["cleaning_suggestions"]),
            )

        session.conversation_history.append({
            "role": "user", "content": request.question,
        })
        session.conversation_history.append({
            "role": "assistant", "content": parsed["explanation"],
        })
        session.code_history.append({
            "code": parsed.get("code", ""),
            "explanation": parsed["explanation"],
            "result": {
                "stdout": exec_result["stdout"] if exec_result else "",
                "figures": exec_result["figures"] if exec_result else [],
            },
        })

        yield _sse_event("done", "")

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _sse_event(event_type: str, data: str) -> str:
    """Format a single SSE event string with the standard event + data fields."""
    return "event: " + event_type + "\ndata: " + data + "\n\n"


# ── Guided ML endpoint (Step 12) ───────────────────────────────────────────


def _validate_ml_stage_progression(current_stage: str | None, requested_stage: str) -> str | None:
    """
    Validate that the requested ML stage is a valid transition from the current stage.

    Returns None if valid, or an error message string if invalid.

    Rules:
    - First stage must be "target" (current_stage is None)
    - Can advance to the next stage in sequence
    - Can restart from any earlier stage (or the same stage)
    - Cannot skip ahead past the next stage

    Failure modes: none — always returns None or an error string.
    """
    if requested_stage not in ML_STAGES:
        return "Invalid stage: " + requested_stage + ". Valid stages: " + ", ".join(ML_STAGES)

    requested_index = ML_STAGES.index(requested_stage)

    # First ML interaction — only "target" is allowed
    if current_stage is None:
        if requested_stage != "target":
            return (
                "ML workflow must start with the 'target' stage. "
                "Requested: " + requested_stage
            )
        return None

    current_index = ML_STAGES.index(current_stage)

    # Restart to an earlier or same stage is always allowed
    if requested_index <= current_index:
        return None

    # Can only advance one step at a time
    if requested_index == current_index + 1:
        return None

    return (
        "Cannot skip from '" + current_stage + "' to '" + requested_stage + "'. "
        "Next valid stage: " + ML_STAGES[current_index + 1]
    )


def _reset_ml_state_from_stage(session, stage: str) -> None:
    """
    Reset all ML state fields for stages after the given stage.

    When a user restarts from an earlier stage, all subsequent state becomes
    invalid and must be cleared. For example, restarting from "target" resets
    features, problem_type, and model_choice.

    Each field is associated with the stage that sets it:
    - target stage sets: ml_target_column, ml_problem_type
    - features stage sets: ml_features
    - model stage sets: ml_model_choice

    When restarting at stage N, all fields set by stages after N are cleared.

    Mutates the session in place.
    """
    stage_index = ML_STAGES.index(stage)

    # Clear fields set by the "features" stage and later
    if stage_index < ML_STAGES.index("features"):
        session.ml_features = None
        session.ml_problem_type = None

    # Clear fields set by the "model" stage and later
    if stage_index < ML_STAGES.index("model"):
        session.ml_model_choice = None


def _get_first_dataframe(session) -> tuple:
    """
    Return the (name, DataFrame) for the first DataFrame in the session.

    Single-DataFrame for MVP — defaults to the first/only entry.

    Failure modes: raises StopIteration if session has no DataFrames.
    """
    name = next(iter(session.dataframes))
    return name, session.dataframes[name]


def _build_ml_prompt(session, stage: str, user_input: str, df_name: str, df) -> str:
    """
    Route to the appropriate prompt builder based on the ML stage.

    Combines the stage-specific prompt with user input as context.
    Returns the complete system prompt for the LLM call.

    Failure modes: raises ValueError for unknown stages (should not happen
    after validation).
    """
    if stage == "target":
        return build_target_selection_prompt(df)

    if stage == "features":
        problem_type = session.ml_problem_type or infer_problem_type(df, session.ml_target_column)
        return build_feature_selection_prompt(df, session.ml_target_column, problem_type)

    if stage == "preprocessing":
        return build_preprocessing_prompt(df, session.ml_target_column, session.ml_features)

    if stage == "model":
        problem_type = session.ml_problem_type or "classification"
        return build_model_selection_prompt(problem_type, df.shape)

    if stage == "training":
        return build_training_prompt(
            session.ml_target_column,
            session.ml_features,
            session.ml_model_choice,
            session.ml_problem_type,
        )

    if stage == "explanation":
        # The explanation stage uses the training result from conversation history.
        # If there's no training output yet, use the user's input as context.
        last_training_output = user_input
        return build_explanation_prompt(last_training_output)

    raise ValueError("Unknown ML stage: " + stage)


def _update_ml_session_state(session, stage: str, parsed: dict, df) -> None:
    """
    Update session ML state based on the completed stage and LLM response.

    Extracts stage-specific fields from the parsed response and stores them
    on the session. Also infers problem type when the target is selected.

    Mutates the session in place.
    """
    session.ml_stage = stage

    if stage == "target":
        target = parsed.get("target_column", "")
        session.ml_target_column = target
        if target and str(target) in df.columns:
            session.ml_problem_type = infer_problem_type(df, target)

    elif stage == "features":
        session.ml_features = parsed.get("features")

    elif stage == "model":
        session.ml_model_choice = parsed.get("model_choice")


@app.post("/api/ml-step")
def ml_step(request: MlStepRequest):
    """
    SSE-streaming Guided ML endpoint. Drives the multi-stage ML workflow:
    target selection → feature selection → preprocessing → model selection →
    training/evaluation → explanation.

    Each request specifies a stage and user input. The endpoint validates
    stage progression, builds a stage-appropriate prompt, calls the LLM,
    optionally executes generated code (training stage), and streams back
    the results.

    SSE event types:
      explanation — LLM's explanation text for this stage
      result      — code execution output (training stage only) as JSON
      ml_state    — updated ML state fields as JSON
      error       — error message if something fails
      done        — signals end of stream

    PRD ref: #5 (Guided ML)
    Tests: backend/tests/test_ml_workflow.py
    """
    session = session_store.get(request.session_id)
    if session is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "session_not_found",
                "detail": "Session not found or has expired.",
            },
        )

    # Validate stage progression before starting the SSE stream.
    # Returns a non-streaming error response so the frontend can handle it cleanly.
    validation_error = _validate_ml_stage_progression(session.ml_stage, request.stage)
    if validation_error is not None:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_stage_progression",
                "detail": validation_error,
            },
        )

    def event_generator():
        df_name, df = _get_first_dataframe(session)

        # Reset state for stages after the requested stage when restarting
        _reset_ml_state_from_stage(session, request.stage)

        system_prompt = _build_ml_prompt(
            session, request.stage, request.user_input, df_name, df,
        )
        messages = [{"role": "user", "content": request.user_input}]

        logger.info(
            "ML step request: session=%s stage=%s user_input_length=%d",
            request.session_id, request.stage, len(request.user_input),
        )

        try:
            raw_response = call_llm_chat(
                system_prompt, messages, session.api_key, session.provider, session.model,
            )
        except Exception as exc:
            logger.error("LLM call failed during ML step: %s", exc)
            yield _sse_event("error", "LLM call failed: " + str(exc))
            yield _sse_event("done", "")
            return

        parsed = parse_ml_step_response(raw_response)

        if "error" in parsed:
            yield _sse_event("error", parsed["error"])
            yield _sse_event("done", "")
            return

        yield _sse_event("explanation", parsed.get("explanation", ""))

        # Training stage: execute the generated code
        if request.stage == "training" and parsed.get("code"):
            exec_result = execute_code(parsed["code"], session.exec_namespace)

            if exec_result["error"]:
                yield _sse_event("error", exec_result["error"])
            else:
                result_payload = json.dumps({
                    "stdout": exec_result["stdout"],
                    "figures": exec_result["figures"],
                })
                yield _sse_event("result", result_payload)

        # Update session state based on the completed stage
        _update_ml_session_state(session, request.stage, parsed, df)

        # Stream the updated ML state so the frontend can update its UI
        ml_state_payload = json.dumps({
            "stage": session.ml_stage,
            "target_column": session.ml_target_column,
            "features": session.ml_features,
            "problem_type": session.ml_problem_type,
            "model_choice": session.ml_model_choice,
        })
        yield _sse_event("ml_state", ml_state_payload)

        # Append to conversation history for LLM context continuity
        session.conversation_history.append({
            "role": "user",
            "content": "[ML " + request.stage + "] " + request.user_input,
        })
        session.conversation_history.append({
            "role": "assistant",
            "content": parsed.get("explanation", ""),
        })

        yield _sse_event("done", "")

    return StreamingResponse(event_generator(), media_type="text/event-stream")
