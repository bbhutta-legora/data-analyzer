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


# ── Response parsing ─────────────────────────────────────────────────────────

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


# ── Orchestrator ──────────────────────────────────────────────────────────────

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
