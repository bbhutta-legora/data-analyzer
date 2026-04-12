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


# ── Retry prompt construction ───────────────────────────────────────────────

TIMEOUT_RETRY_GUIDANCE = (
    "The code timed out. Generate simpler, faster code that avoids "
    "expensive operations (large loops, heavy computations). "
    "Consider sampling or limiting data size.\n\n"
)


def _build_retry_prompt(
    original_question: str,
    failed_code: str,
    error_traceback: str,
) -> str:
    """
    Construct the retry prompt from the original question, failed code, and error.

    Uses string concatenation — not str.format() — so curly braces in user
    questions or error tracebacks (e.g. KeyError: '{col}') don't cause
    KeyError (framework_patterns.md).
    """
    is_timeout = "timed out" in error_traceback.lower()
    extra_guidance = TIMEOUT_RETRY_GUIDANCE if is_timeout else ""

    return (
        'The user asked: """' + original_question + '"""\n'
        "\n"
        "You previously generated the following code, but it failed.\n"
        "\n"
        "Code:\n"
        "```\n"
        + failed_code + "\n"
        "```\n"
        "\n"
        "Error:\n"
        "```\n"
        + error_traceback + "\n"
        "```\n"
        "\n"
        + extra_guidance
        + "Please fix the code and try again. Return valid JSON in the same format as before."
    )


def build_retry_messages(
    original_question: str,
    failed_code: str,
    error_traceback: str,
    conversation_history: list | None = None,
) -> list:
    """
    Build the messages array for a retry LLM call after code failure.

    Includes the conversation history (if any) plus a user message containing
    the original question, the code that failed, and the error traceback.
    For timeout errors, includes guidance to generate simpler/faster code.

    Pure function — no I/O, no side effects. Returns a new list.

    Failure modes: none — always returns a non-empty list.
    """
    if conversation_history is None:
        conversation_history = []

    retry_content = _build_retry_prompt(original_question, failed_code, error_traceback)

    messages = list(conversation_history)
    messages.append({"role": "user", "content": retry_content})
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
