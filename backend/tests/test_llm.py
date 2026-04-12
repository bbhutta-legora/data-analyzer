# tests/test_llm.py
# Tests for LLM prompt construction, code fence stripping, and response parsing.
# Related module: backend/llm.py
# PRD: #2 (initial summary — explanation, cleaning suggestions, suggested questions)
#
# Confirmed behavior list (TEST-STRATEGY Step 1):
#  1. strip_code_fences strips json-tagged code fences
#  2. strip_code_fences strips untagged code fences
#  3. strip_code_fences returns plain JSON unchanged
#  4. strip_code_fences handles trailing prose after closing fence
#  5. build_summary_prompt includes column names from DataFrames
#  6. build_summary_prompt includes shape (row and column counts)
#  7. build_summary_prompt includes dtype information
#  8. build_summary_prompt includes sample row values
#  9. build_summary_prompt includes missing value counts
# 10. build_summary_prompt includes available sandbox library descriptions
# 11. build_summary_prompt handles multiple DataFrames
# 12. build_summary_prompt handles empty DataFrame (0 rows) without crashing
# 13. build_summary_prompt includes response format instructions (JSON field names)
# 14. build_summary_prompt handles special characters in column names
# 15. parse_summary_response extracts all fields from valid JSON
# 16. parse_summary_response defaults missing optional fields to empty arrays
# 17. parse_summary_response returns error for malformed JSON
# 18. parse_summary_response handles JSON wrapped in code fences end-to-end
# 19. parse_summary_response handles extra unexpected fields without crashing
# 20. generate_summary returns structured error when LLM call fails

from unittest.mock import patch

import pandas as pd

from llm import build_summary_prompt, generate_summary, parse_summary_response, strip_code_fences


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_dfs() -> dict[str, pd.DataFrame]:
    """Single-DataFrame dict — the common case (CSV upload)."""
    return {"data": pd.DataFrame({"revenue": [100, 200, 300], "cost": [50, 60, 70]})}


# ── Code fence stripping ─────────────────────────────────────────────────────

def test_strip_code_fences_removes_json_tagged_fences():
    # Behavior 1: strips ```json ... ``` wrapping.
    # Why: LLMs wrap JSON in code fences ~40% of the time; without stripping, json.loads fails.
    raw = '```json\n{"explanation": "test"}\n```'
    result = strip_code_fences(raw)
    assert result == '{"explanation": "test"}'


def test_strip_code_fences_removes_untagged_fences():
    # Behavior 2: strips plain ``` ... ``` wrapping (no language tag).
    # Why: some LLMs omit the language tag; failing to strip causes the same parse crash.
    raw = '```\n{"explanation": "test"}\n```'
    result = strip_code_fences(raw)
    assert result == '{"explanation": "test"}'


def test_strip_code_fences_returns_plain_json_unchanged():
    # Behavior 3: plain JSON with no fences passes through unchanged.
    # Why: if stripping corrupts clean JSON, the happy path breaks.
    raw = '{"explanation": "test"}'
    result = strip_code_fences(raw)
    assert result == '{"explanation": "test"}'


def test_strip_code_fences_handles_trailing_prose():
    # Behavior 4: trailing prose after the closing fence is discarded.
    # Why: LLMs append commentary after fences; an end-anchored regex (framework_patterns.md
    #      anti-pattern) would fail to match, producing a parse error.
    raw = '```json\n{"explanation": "test"}\n```\nHere is some extra commentary about the data.'
    result = strip_code_fences(raw)
    assert result == '{"explanation": "test"}'


# ── Prompt construction ──────────────────────────────────────────────────────

def test_summary_prompt_includes_column_names():
    # Behavior 5: prompt contains all column names from the DataFrame(s).
    # Why: without column names the LLM can't describe the dataset or suggest column-specific
    #      questions — the summary would be generic and useless.
    prompt = build_summary_prompt(make_dfs())
    assert "revenue" in prompt
    assert "cost" in prompt


def test_summary_prompt_includes_shape():
    # Behavior 6: prompt contains row and column counts.
    # Why: the summary must report dataset size accurately; wrong counts mislead the user.
    dfs = {"data": pd.DataFrame({"a": range(100), "b": range(100), "c": range(100)})}
    prompt = build_summary_prompt(dfs)
    assert "100" in prompt
    assert "3" in prompt


def test_summary_prompt_includes_dtypes():
    # Behavior 7: prompt contains dtype strings for each column.
    # Why: the LLM needs dtypes to suggest appropriate analyses (numeric vs categorical)
    #      and to flag type inconsistencies as data quality issues.
    dfs = {"data": pd.DataFrame({"name": ["Alice", "Bob"], "age": [30, 25]})}
    prompt = build_summary_prompt(dfs)
    assert "object" in prompt or "string" in prompt
    assert "int" in prompt


def test_summary_prompt_includes_sample_rows():
    # Behavior 8: prompt contains at least one data value from the frame.
    # Why: sample data lets the LLM reason about actual values, producing better suggested
    #      questions than if it only saw column names and types.
    dfs = {"data": pd.DataFrame({"city": ["London", "Paris", "Tokyo"]})}
    prompt = build_summary_prompt(dfs)
    assert "London" in prompt or "Paris" in prompt or "Tokyo" in prompt


def test_summary_prompt_includes_missing_value_counts():
    # Behavior 9: prompt contains missing value counts.
    # Why: missing values are a core data quality signal (PRD #2); omitting them means the LLM
    #      can't flag cleaning suggestions, which is half the feature's value.
    dfs = {"data": pd.DataFrame({"age": [20.0, None, 40.0, None, 50.0]})}
    prompt = build_summary_prompt(dfs)
    # The prompt should mention that "age" has 2 missing values
    assert "2" in prompt


def test_summary_prompt_includes_sandbox_library_descriptions():
    # Behavior 10: prompt mentions available libraries from SANDBOX_LIBRARY_DESCRIPTIONS.
    # Why: the system prompt must tell the LLM what tools are available so it doesn't suggest
    #      code referencing unavailable libraries in later steps.
    prompt = build_summary_prompt(make_dfs())
    assert "pandas" in prompt.lower()
    assert "matplotlib" in prompt.lower() or "plt" in prompt


def test_summary_prompt_handles_multiple_dataframes():
    # Behavior 11: prompt contains metadata for all DataFrames (multi-sheet Excel).
    # Why: sessions can hold multiple DataFrames; if the prompt only describes one, the user
    #      gets an incomplete summary and the LLM can't suggest cross-DataFrame questions.
    dfs = {
        "Sales": pd.DataFrame({"revenue": [100]}),
        "Costs": pd.DataFrame({"amount": [50]}),
    }
    prompt = build_summary_prompt(dfs)
    assert "Sales" in prompt
    assert "Costs" in prompt
    assert "revenue" in prompt
    assert "amount" in prompt


def test_summary_prompt_with_empty_dataframe():
    # Behavior 12: prompt builder handles a 0-row DataFrame without crashing.
    # Why: a user could upload a headers-only CSV; crashing here produces a 500 instead of
    #      a helpful summary saying "your dataset has no rows."
    dfs = {"data": pd.DataFrame({"col1": pd.Series(dtype="float64"), "col2": pd.Series(dtype="str")})}
    prompt = build_summary_prompt(dfs)
    assert isinstance(prompt, str)
    assert len(prompt) > 0
    assert "col1" in prompt


def test_summary_prompt_includes_response_format_instructions():
    # Behavior 13: prompt tells the LLM to respond in JSON with specific field names.
    # Why: without explicit format instructions, the LLM returns freeform prose instead of
    #      parseable JSON, breaking the entire summary feature.
    prompt = build_summary_prompt(make_dfs())
    assert "explanation" in prompt
    assert "cleaning_suggestions" in prompt
    assert "suggested_questions" in prompt


def test_summary_prompt_handles_special_characters_in_column_names():
    # Behavior 14: column names with curly braces, quotes, or other format-special characters
    # don't crash the prompt builder.
    # Why: real-world datasets have messy column names; if the prompt builder uses
    #      str.format(), a column named {revenue} causes a KeyError (framework_patterns.md).
    dfs = {"data": pd.DataFrame({"{tricky}": [1, 2], 'col "quoted"': [3, 4]})}
    prompt = build_summary_prompt(dfs)
    assert isinstance(prompt, str)
    assert len(prompt) > 0


# ── Response parsing ─────────────────────────────────────────────────────────

def test_parse_summary_response_extracts_all_fields():
    # Behavior 15: valid JSON with all three fields is correctly extracted.
    # Why: these fields feed directly into the frontend DataSummary component; wrong parsing
    #      means the user sees nothing or garbled data after upload.
    raw = '''{
        "explanation": "This dataset contains sales data.",
        "cleaning_suggestions": [
            {"description": "3 duplicate rows found", "options": ["Remove", "Keep"]}
        ],
        "suggested_questions": ["What is the average revenue?", "Show the distribution of cost"]
    }'''
    parsed = parse_summary_response(raw)
    assert parsed["explanation"] == "This dataset contains sales data."
    assert len(parsed["cleaning_suggestions"]) == 1
    assert parsed["cleaning_suggestions"][0]["description"] == "3 duplicate rows found"
    assert len(parsed["suggested_questions"]) == 2


def test_parse_summary_response_defaults_missing_optional_fields():
    # Behavior 16: missing optional fields default to empty arrays.
    # Why: the LLM may omit these for simple datasets; crashing on a missing key would break
    #      the upload flow entirely.
    raw = '{"explanation": "Simple dataset."}'
    parsed = parse_summary_response(raw)
    assert parsed["explanation"] == "Simple dataset."
    assert parsed["cleaning_suggestions"] == []
    assert parsed["suggested_questions"] == []


def test_parse_summary_response_returns_error_for_malformed_json():
    # Behavior 17: non-JSON input returns a dict with an "error" key.
    # Why: if the LLM returns prose, we need a structured error rather than an unhandled
    #      exception that surfaces as a 500 to the user.
    raw = "this is not json at all"
    parsed = parse_summary_response(raw)
    assert "error" in parsed


def test_parse_summary_response_handles_code_fenced_json():
    # Behavior 18: JSON wrapped in code fences is still parsed correctly (strip + parse).
    # Why: this is the actual call path — strip then parse. Testing them composed catches
    #      integration bugs between the two functions.
    raw = '```json\n{"explanation": "Fenced response.", "suggested_questions": ["Q1"]}\n```'
    parsed = parse_summary_response(raw)
    assert parsed["explanation"] == "Fenced response."
    assert parsed["suggested_questions"] == ["Q1"]
    assert parsed["cleaning_suggestions"] == []


def test_parse_summary_response_ignores_extra_fields():
    # Behavior 19: extra unexpected fields don't crash the parser.
    # Why: the LLM may include fields we didn't ask for; crashing would break the feature
    #      when the model decides to be verbose.
    raw = '{"explanation": "Test.", "extra_field": 123, "another": true}'
    parsed = parse_summary_response(raw)
    assert parsed["explanation"] == "Test."
    assert parsed["cleaning_suggestions"] == []
    assert parsed["suggested_questions"] == []


# ── generate_summary orchestration ───────────────────────────────────────────

def test_generate_summary_returns_error_on_llm_failure():
    # Behavior 20: when the LLM API call raises an exception, generate_summary returns a
    # dict with an "error" key rather than propagating the exception.
    # Why: without this, an LLM failure during upload crashes the endpoint with a 500.
    #      The user loses their file parse results even though parsing succeeded.
    with patch("llm.call_llm") as mock_call:
        mock_call.side_effect = Exception("API rate limit exceeded")
        result = generate_summary(make_dfs(), "sk-test", "openai", "gpt-5.4-mini")
        assert "error" in result
