# llm.py
# LLM integration: prompt construction, provider dispatch, response parsing.
# Supports: PRD #2 (initial summary), #3 (Q&A — added in Step 8),
#           #4 (cleaning suggestions), #5 (guided ML — added in Step 12)
# Key deps: sandbox_libraries.py (library descriptions for system prompt),
#           providers.py (model IDs), openai/anthropic SDKs (deferred imports)
#
# Design: pure functions (build_*_prompt, parse_*_response, strip_code_fences)
#         are separated from I/O functions (call_llm, generate_summary).
#         This makes the pure functions trivially testable without mocks.
#
# Architecture ref: "LLM Prompting" in planning/architecture.md §7
# Tests: backend/tests/test_llm.py

import json
import logging
import re

from sandbox_libraries import SANDBOX_LIBRARY_DESCRIPTIONS

logger = logging.getLogger(__name__)

# ── Code fence stripping ─────────────────────────────────────────────────────
# LLMs non-deterministically wrap JSON in markdown code fences.
# This regex extracts the first fenced block; trailing prose is ignored.
# CRITICAL: no end-of-string anchor ($) — see framework_patterns.md.

_CODE_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)


def strip_code_fences(text: str) -> str:
    """
    Strip markdown code fences if present, return inner content.

    Handles ```json ... ``` and plain ``` ... ``` wrapping.
    If no fences are found, returns the original text unchanged.

    Failure modes: none — always returns a string.
    """
    match = _CODE_FENCE_RE.match(text)
    return match.group(1).strip() if match else text


# ── Prompt construction ──────────────────────────────────────────────────────

# Uses string concatenation rather than str.format() or f-strings to avoid
# KeyError when column names contain curly braces (framework_patterns.md).
# SANDBOX_LIBRARY_DESCRIPTIONS comes from sandbox_libraries.py — the single
# source of truth shared with session.py's exec namespace.

MAX_SAMPLE_ROWS = 5


def _build_dataset_section(name: str, df) -> str:
    """Build a metadata section for a single named DataFrame."""
    rows, cols = df.shape
    lines = [
        'Dataset: "' + name + '"',
        "  Rows: " + str(rows),
        "  Columns: " + str(cols),
    ]

    dtype_lines = []
    missing_lines = []
    for col in df.columns:
        col_str = str(col)
        dtype_str = str(df[col].dtype)
        missing_count = int(df[col].isnull().sum())
        dtype_lines.append("    " + col_str + ": " + dtype_str)
        if missing_count > 0:
            missing_lines.append("    " + col_str + ": " + str(missing_count) + " missing")

    lines.append("  Column dtypes:")
    lines.extend(dtype_lines)

    if missing_lines:
        lines.append("  Missing values:")
        lines.extend(missing_lines)
    else:
        lines.append("  Missing values: none")

    if rows > 0:
        sample = df.head(MAX_SAMPLE_ROWS)
        lines.append("  Sample rows (first " + str(min(rows, MAX_SAMPLE_ROWS)) + "):")
        lines.append("    " + sample.to_string(index=False).replace("\n", "\n    "))

    return "\n".join(lines)


def _build_library_section() -> str:
    """List available sandbox libraries for the LLM system prompt."""
    lines = ["Available libraries in the analysis environment:"]
    for short_name, description in SANDBOX_LIBRARY_DESCRIPTIONS.items():
        lines.append("  " + short_name + " — " + description)
    lines.append('DataFrames are accessible as dfs["<name>"] (a Python dict).')
    return "\n".join(lines)


_RESPONSE_FORMAT_INSTRUCTIONS = """
Respond with a JSON object containing exactly these fields:
{
  "explanation": "A clear, beginner-friendly summary of the dataset: what it contains, its structure, any notable patterns or characteristics.",
  "cleaning_suggestions": [
    {
      "description": "A data quality issue found (e.g., duplicate rows, missing values, type inconsistencies)",
      "options": ["Option A to fix it", "Option B to fix it"]
    }
  ],
  "suggested_questions": [
    "3-5 interesting questions a data scientist could explore with this dataset"
  ]
}

Rules:
- Return ONLY the JSON object, no other text.
- cleaning_suggestions may be an empty array if no issues are found.
- suggested_questions should be specific to THIS dataset (reference actual column names).
- Each cleaning suggestion must include at least 2 actionable options.
""".strip()


def build_summary_prompt(dataframes: dict) -> str:
    """
    Construct the full summary prompt from a dict of named DataFrames.

    Includes: role definition, dataset metadata (columns, dtypes, shape, sample rows,
    missing values), available sandbox libraries, and response format instructions.

    Uses string concatenation — not str.format() — so column names containing
    curly braces don't cause KeyError (framework_patterns.md).

    Failure modes: none — always returns a non-empty string, even for empty DataFrames.
    """
    sections = [
        "You are a data analysis assistant helping junior data scientists understand their datasets.",
        "Analyze the following dataset(s) and provide an initial summary.",
        "",
    ]

    for name, df in dataframes.items():
        sections.append(_build_dataset_section(name, df))
        sections.append("")

    sections.append(_build_library_section())
    sections.append("")
    sections.append(_RESPONSE_FORMAT_INSTRUCTIONS)

    return "\n".join(sections)


# ── Chat prompt construction ─────────────────────────────────────────────────

_CHAT_RESPONSE_FORMAT_INSTRUCTIONS = """
Respond with a JSON object containing exactly these fields:
{
  "code": "<Python code to execute for this analysis>",
  "explanation": "<A clear, beginner-friendly explanation of what the code does and what the results mean>",
  "cleaning_suggestions": [
    {
      "description": "A data quality issue relevant to this analysis",
      "options": ["Option A to fix it", "Option B to fix it"]
    }
  ]
}

Rules:
- Return ONLY the JSON object, no other text.
- The "code" field must contain valid Python that can be executed in the sandbox.
- Access DataFrames using dfs["<name>"] (e.g., dfs["sales"], dfs["costs"]).
- cleaning_suggestions may be an empty array if no issues are found.
- Each cleaning suggestion must include at least 2 actionable options.
- If the question cannot be answered with the available data, explain why in the
  explanation field and provide an empty string for code.
""".strip()


def build_chat_system_prompt(dataframes: dict) -> str:
    """
    Construct the system prompt for chat Q&A from a dict of named DataFrames.

    Includes: role definition, dataset metadata (columns, dtypes, shape, sample rows,
    missing values), available sandbox libraries, and response format instructions.

    Reuses _build_dataset_section and _build_library_section from the summary flow.
    Uses string concatenation — not str.format() — so column names containing
    curly braces don't cause KeyError (framework_patterns.md).

    Failure modes: none — always returns a non-empty string.
    """
    sections = [
        "You are a data analysis assistant helping junior data scientists "
        "explore and analyze their datasets.",
        "When the user asks a question, generate Python code to answer it "
        "and provide a clear explanation.",
        "",
    ]

    for name, df in dataframes.items():
        sections.append(_build_dataset_section(name, df))
        sections.append("")

    sections.append(_build_library_section())
    sections.append("")
    sections.append(_CHAT_RESPONSE_FORMAT_INSTRUCTIONS)

    return "\n".join(sections)


def build_chat_messages(question: str, conversation_history: list) -> list:
    """
    Build the messages array for a chat LLM call.

    Appends the new user question to the conversation history.
    The system prompt is handled separately (not in this array) because
    OpenAI and Anthropic pass it differently — see call_llm_chat.

    Returns a new list — does not modify the input history.

    Failure modes: none — always returns a non-empty list.
    """
    messages = list(conversation_history)
    messages.append({"role": "user", "content": question})
    return messages


def parse_chat_response(raw: str) -> dict:
    """
    Parse an LLM chat response into a structured dict.

    Strips code fences before parsing (LLMs wrap JSON non-deterministically).
    Returns a dict with code, explanation, and cleaning_suggestions.
    Missing optional fields default to safe values.
    Malformed JSON returns {"error": "<message>"}.

    Failure modes:
    - Malformed JSON → returns {"error": ...} instead of raising
    - Missing fields → safe defaults via .get()
    """
    cleaned = strip_code_fences(raw)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse LLM chat response as JSON: %s", exc)
        return {"error": "Invalid JSON in LLM response: " + str(exc)}

    return {
        "code": parsed.get("code", ""),
        "explanation": parsed.get("explanation", ""),
        "cleaning_suggestions": parsed.get("cleaning_suggestions", []),
    }


# ── History truncation ───────────────────────────────────────────────────────

# Approximate token estimation: word_count * 1.3
# REVIEW: if this causes premature truncation or token overflows, switch to tiktoken.
TOKENS_PER_WORD_ESTIMATE = 1.3


def _estimate_tokens(text: str) -> int:
    """Estimate the token count of a string using word count * 1.3."""
    word_count = len(text.split())
    return int(word_count * TOKENS_PER_WORD_ESTIMATE)


def truncate_history(history: list, max_tokens: int) -> list:
    """
    Sliding-window truncation that drops oldest messages when the total
    estimated token count exceeds max_tokens.

    Scans from newest to oldest, accumulating messages until the budget
    is exhausted. Always preserves the most recent message — even if it
    alone exceeds max_tokens.

    Returns a new list; does not modify the input.

    Failure modes: none — empty list returns empty list.
    """
    if not history:
        return []

    result = [history[-1]]
    remaining_tokens = max_tokens - _estimate_tokens(history[-1].get("content", ""))

    for message in reversed(history[:-1]):
        message_tokens = _estimate_tokens(message.get("content", ""))
        if message_tokens <= remaining_tokens:
            result.insert(0, message)
            remaining_tokens -= message_tokens
        else:
            break

    return result


# ── Summary response parsing ─────────────────────────────────────────────────

def parse_summary_response(raw: str) -> dict:
    """
    Parse an LLM summary response into a structured dict.

    Strips code fences before parsing (LLMs wrap JSON non-deterministically).
    Returns a dict with explanation, cleaning_suggestions, and suggested_questions.
    Missing optional fields default to empty arrays.
    Malformed JSON returns {"error": "<message>"}.

    Failure modes:
    - Malformed JSON → returns {"error": ...} instead of raising
    - Missing fields → safe defaults via .get()
    """
    cleaned = strip_code_fences(raw)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse LLM summary response as JSON: %s", exc)
        return {"error": "Invalid JSON in LLM response: " + str(exc)}

    return {
        "explanation": parsed.get("explanation", ""),
        "cleaning_suggestions": parsed.get("cleaning_suggestions", []),
        "suggested_questions": parsed.get("suggested_questions", []),
    }


# ── LLM API call ─────────────────────────────────────────────────────────────

# Low temperature for summaries — we want factual, deterministic descriptions
# of the dataset, not creative prose.
LLM_SUMMARY_TEMPERATURE = 0.3

# Anthropic requires an explicit max_tokens. 2048 is sufficient for a summary
# with explanation + cleaning suggestions + suggested questions.
LLM_SUMMARY_MAX_TOKENS = 2048


def call_llm(prompt: str, api_key: str, provider: str, model: str) -> str:
    """
    Send a prompt to the LLM and return the raw response text.

    Dispatches to OpenAI or Anthropic SDK based on provider.
    SDKs are imported at call time (not module level) so only the selected
    provider's SDK is loaded — both are large and slow to import.

    Failure modes:
    - AuthenticationError → propagates (key was validated at BYOK step)
    - RateLimitError, network errors → propagate to caller for handling
    """
    if provider == "anthropic":
        return _call_anthropic(prompt, api_key, model)
    return _call_openai(prompt, api_key, model)


def _call_openai(prompt: str, api_key: str, model: str) -> str:
    """Call OpenAI Chat Completions API with the summary prompt."""
    import openai
    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=LLM_SUMMARY_TEMPERATURE,
    )
    return response.choices[0].message.content or ""


def _call_anthropic(prompt: str, api_key: str, model: str) -> str:
    """Call Anthropic Messages API with the summary prompt."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=LLM_SUMMARY_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


# ── Chat LLM call ────────────────────────────────────────────────────────────

# Same low temperature as summaries — we want factual analysis code, not creative.
LLM_CHAT_TEMPERATURE = 0.3

# Anthropic requires explicit max_tokens. 4096 gives room for complex code +
# detailed explanation + cleaning suggestions.
LLM_CHAT_MAX_TOKENS = 4096


def call_llm_chat(
    system_prompt: str,
    messages: list,
    api_key: str,
    provider: str,
    model: str,
) -> str:
    """
    Send a multi-turn chat request to the LLM and return the raw response text.

    Dispatches to OpenAI or Anthropic SDK based on provider.
    Handles the system prompt differently per provider:
    - OpenAI: system prompt is the first message with role "system"
    - Anthropic: system prompt is a separate `system` parameter

    SDKs are imported at call time — see call_llm for rationale.

    Failure modes:
    - AuthenticationError → propagates (key was validated at BYOK step)
    - RateLimitError, network errors → propagate to caller for handling
    """
    if provider == "anthropic":
        return _call_anthropic_chat(system_prompt, messages, api_key, model)
    return _call_openai_chat(system_prompt, messages, api_key, model)


def _call_openai_chat(
    system_prompt: str, messages: list, api_key: str, model: str,
) -> str:
    """Call OpenAI Chat Completions API with system prompt and message history."""
    import openai

    client = openai.OpenAI(api_key=api_key)
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    response = client.chat.completions.create(
        model=model,
        messages=full_messages,
        temperature=LLM_CHAT_TEMPERATURE,
    )
    return response.choices[0].message.content or ""


def _call_anthropic_chat(
    system_prompt: str, messages: list, api_key: str, model: str,
) -> str:
    """Call Anthropic Messages API with system prompt and message history."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=LLM_CHAT_MAX_TOKENS,
        system=system_prompt,
        messages=messages,
    )
    return response.content[0].text


# ── Summary orchestrator ─────────────────────────────────────────────────────

def generate_summary(
    dataframes: dict,
    api_key: str,
    provider: str,
    model: str,
) -> dict:
    """
    Generate an LLM-powered summary of the dataset(s).

    Builds the prompt, calls the LLM, and parses the response.
    On any exception (API error, network failure, rate limit), returns
    {"error": "<message>"} so the upload endpoint can still return dataset
    metadata even if the summary fails.

    Failure modes:
    - LLM API failure → returns {"error": ...}
    - Malformed LLM response → returns {"error": ...} (via parse_summary_response)
    """
    prompt = build_summary_prompt(dataframes)

    logger.info(
        "Calling LLM for initial summary: provider=%s model=%s prompt_length=%d",
        provider, model, len(prompt),
    )

    try:
        raw_response = call_llm(prompt, api_key, provider, model)
    except Exception as exc:
        logger.error("LLM call failed during summary generation: %s", exc)
        return {"error": "Summary generation failed: " + str(exc)}

    logger.info("LLM summary response received: length=%d", len(raw_response))
    return parse_summary_response(raw_response)


# ── Guided ML workflow (PRD #5) ─────────────────────────────────────────────

# Threshold for distinguishing classification from regression on numeric columns.
# Numeric columns with this many or fewer unique values are treated as classification
# (covers binary labels like 0/1 and small ordinal categories like 1-5 ratings).
CLASSIFICATION_UNIQUE_VALUE_THRESHOLD = 10

# Ordered list of ML stages — used for progression validation.
ML_STAGES = ["target", "features", "preprocessing", "model", "training", "explanation"]


def infer_problem_type(df, target_column: str) -> str:
    """
    Infer whether a target column represents a classification or regression problem.

    Pure heuristic — no LLM call. Rules:
    1. Object (string) or boolean dtype → classification
    2. Numeric dtype with <= CLASSIFICATION_UNIQUE_VALUE_THRESHOLD unique values → classification
    3. Otherwise → regression

    Failure modes: none — always returns "classification" or "regression".
    """
    col = df[target_column]

    if col.dtype == "object" or col.dtype == "bool":
        return "classification"

    unique_count = col.nunique()
    if unique_count <= CLASSIFICATION_UNIQUE_VALUE_THRESHOLD:
        return "classification"

    return "regression"


def build_target_selection_prompt(df) -> str:
    """
    Build a prompt that asks the LLM to help the user select a target column.

    Includes column names, dtypes, unique value counts, and sample values so
    the LLM can make an informed recommendation.

    Uses string concatenation — not str.format() — so column names containing
    curly braces don't cause KeyError (framework_patterns.md).

    Failure modes: none — always returns a non-empty string.
    """
    lines = [
        "You are a data analysis assistant helping a user build a predictive model.",
        "The user needs to choose a target column (the column they want to predict).",
        "",
        "Available columns:",
    ]

    for col in df.columns:
        col_str = str(col)
        dtype_str = str(df[col].dtype)
        unique_count = int(df[col].nunique())
        sample_values = df[col].dropna().head(MAX_SAMPLE_ROWS).tolist()
        sample_str = ", ".join(str(v) for v in sample_values)

        lines.append(
            "  " + col_str + " (dtype: " + dtype_str
            + ", unique values: " + str(unique_count)
            + ", sample: " + sample_str + ")"
        )

    lines.append("")
    lines.append("Based on the data, recommend which column would be a good prediction target.")
    lines.append("Explain why in simple terms.")
    lines.append("")
    lines.append(_ML_TARGET_RESPONSE_FORMAT)

    return "\n".join(lines)


def build_feature_selection_prompt(df, target_column: str, problem_type: str) -> str:
    """
    Build a prompt that helps the user select feature columns for their model.

    Lists all non-target columns with metadata. Includes the problem type so
    the LLM can tailor its feature recommendations.

    Uses string concatenation — not str.format() — so column names containing
    curly braces don't cause KeyError (framework_patterns.md).

    Failure modes: none — always returns a non-empty string.
    """
    lines = [
        "You are a data analysis assistant helping a user select features for a "
        + problem_type + " model.",
        "The target column is: " + str(target_column),
        "",
        "Available feature columns (excluding the target):",
    ]

    for col in df.columns:
        if str(col) == str(target_column):
            continue
        col_str = str(col)
        dtype_str = str(df[col].dtype)
        unique_count = int(df[col].nunique())
        missing_count = int(df[col].isnull().sum())
        missing_info = ""
        if missing_count > 0:
            missing_info = ", missing: " + str(missing_count)

        lines.append(
            "  " + col_str + " (dtype: " + dtype_str
            + ", unique values: " + str(unique_count)
            + missing_info + ")"
        )

    lines.append("")
    lines.append(
        "Recommend which features to include and explain why. "
        "Consider relevance to the target, data quality, and potential multicollinearity."
    )
    lines.append("")
    lines.append(_ML_FEATURE_RESPONSE_FORMAT)

    return "\n".join(lines)


def build_preprocessing_prompt(df, target_column: str, features: list) -> str:
    """
    Build a prompt that guides preprocessing decisions for the selected features.

    Identifies encoding needs for categorical columns, scaling needs for numeric
    columns, and missing value handling. Lists concrete facts about each column
    so the LLM can make specific recommendations.

    Uses string concatenation — not str.format() — so column names containing
    curly braces don't cause KeyError (framework_patterns.md).

    Failure modes: none — always returns a non-empty string.
    """
    lines = [
        "You are a data analysis assistant helping a user prepare data for machine learning.",
        "Target column: " + str(target_column),
        "Selected features: " + ", ".join(str(f) for f in features),
        "",
        "Column details:",
    ]

    all_columns = [target_column] + list(features)
    for col_name in all_columns:
        col_str = str(col_name)
        if col_str not in df.columns:
            continue
        col = df[col_str]
        dtype_str = str(col.dtype)
        missing_count = int(col.isnull().sum())
        total_rows = len(df)

        detail = "  " + col_str + " — dtype: " + dtype_str
        if missing_count > 0:
            pct = round(missing_count / total_rows * 100, 1)
            detail = detail + ", missing values: " + str(missing_count) + " (" + str(pct) + "%)"
        else:
            detail = detail + ", no missing values"

        if col.dtype == "object":
            unique_count = int(col.nunique())
            detail = detail + ", categorical with " + str(unique_count) + " unique values"

        lines.append(detail)

    lines.append("")
    lines.append(
        "Recommend preprocessing steps: encoding for categorical columns, "
        "scaling for numeric columns, and how to handle any missing values. "
        "Explain each recommendation in simple terms."
    )
    lines.append("")
    lines.append(_ML_PREPROCESSING_RESPONSE_FORMAT)

    return "\n".join(lines)


def build_model_selection_prompt(problem_type: str, df_shape: tuple) -> str:
    """
    Build a prompt that helps the user choose a model based on problem type and data size.

    Takes problem_type and df_shape (rows, columns) as separate arguments rather
    than the full DataFrame — keeps this function pure and decoupled from pandas.

    Failure modes: none — always returns a non-empty string.
    """
    rows, cols = df_shape
    lines = [
        "You are a data analysis assistant helping a user choose a machine learning model.",
        "",
        "Problem type: " + problem_type,
        "Dataset size: " + str(rows) + " rows, " + str(cols) + " columns",
        "",
        "Suggest 2-3 appropriate scikit-learn models for this problem. For each model:",
        "- Name the model and its sklearn class",
        "- Explain in simple terms when it works well",
        "- Note any limitations or considerations",
        "",
        "Recommend one model as the best starting point and explain why.",
        "",
    ]
    lines.append(_ML_MODEL_RESPONSE_FORMAT)

    return "\n".join(lines)


def build_training_prompt(
    target_column: str,
    features: list,
    model_choice: str,
    problem_type: str,
) -> str:
    """
    Build a prompt that asks the LLM to generate sklearn training code.

    The generated code should use dfs["<name>"] to access the DataFrame,
    perform a train/test split, fit the model, and print evaluation metrics.

    Uses string concatenation — not str.format() — so column names containing
    curly braces don't cause KeyError (framework_patterns.md).

    Failure modes: none — always returns a non-empty string.
    """
    features_str = ", ".join(str(f) for f in features)
    lines = [
        "You are a data analysis assistant. Generate Python code to train a machine learning model.",
        "",
        "Problem type: " + problem_type,
        "Target column: " + str(target_column),
        "Feature columns: " + features_str,
        "Model: " + str(model_choice),
        "",
        "Requirements for the generated code:",
        '- Access the DataFrame using dfs["<name>"] (first available key in the dfs dict)',
        "- Handle categorical features with appropriate encoding (e.g., pd.get_dummies or LabelEncoder)",
        "- Split data into train/test sets (80/20 split)",
        "- Train the specified model using sklearn",
        "- Print evaluation metrics:",
    ]

    if problem_type == "classification":
        lines.append("  - accuracy, precision, recall, F1-score")
        lines.append("  - confusion matrix")
    else:
        lines.append("  - R-squared (R2)")
        lines.append("  - Mean Squared Error (MSE)")
        lines.append("  - Mean Absolute Error (MAE)")

    lines.append("- Use print() for all output (not return statements)")
    lines.append("- The code must be self-contained and executable in the sandbox")
    lines.append("")
    lines.append(_ML_TRAINING_RESPONSE_FORMAT)

    return "\n".join(lines)


def build_explanation_prompt(training_result: str) -> str:
    """
    Build a prompt that asks the LLM to explain training results in plain English.

    Takes the raw training output (stdout from code execution) and asks the LLM
    to summarize what the model learned, interpret the metrics, and note caveats.

    Failure modes: none — always returns a non-empty string.
    """
    lines = [
        "You are a data analysis assistant. Explain the following machine learning "
        "training results in plain English for a junior data scientist.",
        "",
        "Training output:",
        training_result,
        "",
        "Provide:",
        "- A summary of how well the model performed",
        "- What the metrics mean in practical terms",
        "- Any caveats or limitations to be aware of",
        "- Suggestions for potential improvements",
        "",
        _ML_EXPLANATION_RESPONSE_FORMAT,
    ]

    return "\n".join(lines)


# ── ML response format instructions ─────────────────────────────────────────

_ML_TARGET_RESPONSE_FORMAT = """Respond with a JSON object containing exactly these fields:
{
  "explanation": "Your recommendation and reasoning in plain English",
  "target_column": "the_recommended_column_name",
  "next_stage": "features"
}

Rules:
- Return ONLY the JSON object, no other text.
- target_column must be one of the actual column names listed above.
""".strip()

_ML_FEATURE_RESPONSE_FORMAT = """Respond with a JSON object containing exactly these fields:
{
  "explanation": "Your feature recommendations and reasoning",
  "features": ["feature1", "feature2"],
  "next_stage": "preprocessing"
}

Rules:
- Return ONLY the JSON object, no other text.
- features must be an array of actual column names from the list above.
""".strip()

_ML_PREPROCESSING_RESPONSE_FORMAT = """Respond with a JSON object containing exactly these fields:
{
  "explanation": "Your preprocessing recommendations and reasoning",
  "preprocessing_steps": ["step 1 description", "step 2 description"],
  "next_stage": "model"
}

Rules:
- Return ONLY the JSON object, no other text.
""".strip()

_ML_MODEL_RESPONSE_FORMAT = """Respond with a JSON object containing exactly these fields:
{
  "explanation": "Your model recommendations and reasoning",
  "model_choice": "model_name (e.g., random_forest, logistic_regression, linear_regression, gradient_boosting)",
  "next_stage": "training"
}

Rules:
- Return ONLY the JSON object, no other text.
- model_choice should be a short identifier for the recommended model.
""".strip()

_ML_TRAINING_RESPONSE_FORMAT = """Respond with a JSON object containing exactly these fields:
{
  "explanation": "Brief explanation of what the code does",
  "code": "the complete Python code to execute",
  "next_stage": "explanation"
}

Rules:
- Return ONLY the JSON object, no other text.
- The code field must contain valid, executable Python.
""".strip()

_ML_EXPLANATION_RESPONSE_FORMAT = """Respond with a JSON object containing exactly these fields:
{
  "explanation": "Your plain-English explanation of the results",
  "next_stage": null
}

Rules:
- Return ONLY the JSON object, no other text.
- next_stage should be null since this is the final stage.
""".strip()


def parse_ml_step_response(raw: str) -> dict:
    """
    Parse an LLM ML step response into a structured dict.

    Strips code fences before parsing (LLMs wrap JSON non-deterministically).
    Passes through all fields from the parsed JSON — each stage returns different
    fields (target_column, features, model_choice, code, etc.) and the endpoint
    handler extracts what it needs based on the current stage.

    Missing "explanation" defaults to empty string. All other fields are passed
    through as-is from the LLM response.

    Failure modes:
    - Malformed JSON → returns {"error": "<message>"} instead of raising
    """
    cleaned = strip_code_fences(raw)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse LLM ML step response as JSON: %s", exc)
        return {"error": "Invalid JSON in LLM response: " + str(exc)}

    # Ensure explanation always has a safe default
    if "explanation" not in parsed:
        parsed["explanation"] = ""

    return parsed
