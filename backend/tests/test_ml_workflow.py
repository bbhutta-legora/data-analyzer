# tests/test_ml_workflow.py
# Tests for the Guided ML workflow backend: prompt builders, response parsing,
# problem type inference, stage progression, and the /api/ml-step endpoint.
# Related modules: backend/llm.py, backend/main.py, backend/session.py
# PRD: #5 (Guided ML)
#
# Confirmed behavior list (TEST-STRATEGY Steps 1-2):
#  1. infer_problem_type returns "classification" for categorical (object) dtype
#  2. infer_problem_type returns "regression" for numeric with many unique values
#  3. infer_problem_type returns "classification" for numeric with <= 10 unique values
#  4. infer_problem_type returns "classification" for boolean dtype
#  5. build_target_selection_prompt includes all column names
#  6. build_target_selection_prompt includes dtype information
#  7. build_target_selection_prompt includes sample values
#  8. build_feature_selection_prompt includes non-target column names
#  9. build_feature_selection_prompt includes problem type
# 10. build_preprocessing_prompt includes target and feature column names
# 11. build_preprocessing_prompt mentions missing values for columns that have them
# 12. build_model_selection_prompt includes problem type
# 13. build_model_selection_prompt includes dataset shape information
# 14. build_training_prompt includes target, features, model choice, and problem type
# 15. build_explanation_prompt includes training result context
# 16. parse_ml_step_response extracts structured fields from valid JSON
# 17. parse_ml_step_response returns error for malformed JSON
# 18. parse_ml_step_response handles JSON wrapped in code fences
# 19. Stage progression: cannot skip from "target" to "training"
# 20. Stage progression: sequential advancement works (target -> features)
# 21. Stage restart: going to "target" from "model" resets subsequent state
# 22. Stage progression: first stage must be "target"
# 23. /api/ml-step returns SSE stream with explanation event
# 24. /api/ml-step returns 404 for unknown session_id
# 25. /api/ml-step returns 400 for invalid stage progression
# 26. /api/ml-step updates session ML state after each stage
# 27. /api/ml-step routes training stage through code execution

import json
from unittest.mock import patch

import pandas as pd

from llm import (
    build_explanation_prompt,
    build_feature_selection_prompt,
    build_model_selection_prompt,
    build_preprocessing_prompt,
    build_target_selection_prompt,
    build_training_prompt,
    infer_problem_type,
    parse_ml_step_response,
)
from main import app, session_store

from fastapi.testclient import TestClient

client = TestClient(app)


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_ml_df() -> pd.DataFrame:
    """DataFrame suitable for ML workflow testing."""
    return pd.DataFrame({
        "price": [100.0, 200.0, 300.0, 400.0, 500.0,
                  600.0, 700.0, 800.0, 900.0, 1000.0, 1100.0],
        "size": [50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150],
        "color": ["red", "blue", "red", "green", "blue",
                  "red", "blue", "green", "red", "blue", "green"],
        "sold": [1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0],
    })


def make_ml_dfs() -> dict[str, pd.DataFrame]:
    """Single-DataFrame dict for ML workflow testing."""
    return {"products": make_ml_df()}


def create_ml_session(
    dfs: dict[str, pd.DataFrame] | None = None,
    api_key: str = "sk-test",
    provider: str = "openai",
    model: str = "gpt-5.4-mini",
) -> str:
    """Create a session in the shared store and return its session_id."""
    if dfs is None:
        dfs = make_ml_dfs()
    return session_store.create(dfs, api_key=api_key, provider=provider, model=model)


def parse_sse_events(response_text: str) -> list[dict]:
    """
    Parse SSE event stream text into a list of {event, data} dicts.

    Handles the standard SSE format:
        event: <type>
        data: <payload>
        <blank line>
    """
    events: list[dict] = []
    current_event: str | None = None
    current_data: list[str] = []

    for line in response_text.split("\n"):
        if line.startswith("event: "):
            if current_event is not None:
                events.append({
                    "event": current_event,
                    "data": "\n".join(current_data),
                })
            current_event = line[len("event: "):]
            current_data = []
        elif line.startswith("data: "):
            current_data.append(line[len("data: "):])
        elif line == "" and current_event is not None:
            events.append({
                "event": current_event,
                "data": "\n".join(current_data),
            })
            current_event = None
            current_data = []

    if current_event is not None:
        events.append({
            "event": current_event,
            "data": "\n".join(current_data),
        })

    return events


# Pre-built mock responses used across endpoint tests.

MOCK_ML_TARGET_RESPONSE: str = json.dumps({
    "explanation": "I recommend 'price' as the target column because it represents the value you want to predict.",
    "target_column": "price",
    "next_stage": "features",
})

MOCK_ML_FEATURE_RESPONSE: str = json.dumps({
    "explanation": "Based on correlation analysis, I suggest using 'size' and 'color' as features.",
    "features": ["size", "color"],
    "next_stage": "preprocessing",
})

MOCK_ML_PREPROCESSING_RESPONSE: str = json.dumps({
    "explanation": "The 'color' column needs one-hot encoding. No missing values found.",
    "preprocessing_steps": ["one-hot encode color", "standard scale size"],
    "next_stage": "model",
})

MOCK_ML_MODEL_RESPONSE: str = json.dumps({
    "explanation": "For regression with a small dataset, Random Forest is a good choice.",
    "model_choice": "random_forest",
    "next_stage": "training",
})

MOCK_ML_TRAINING_RESPONSE: str = json.dumps({
    "explanation": "Training a Random Forest regressor on the prepared data.",
    "code": "print('training complete')",
    "next_stage": "explanation",
})

MOCK_ML_EXPLANATION_RESPONSE: str = json.dumps({
    "explanation": "The model achieved an R-squared of 0.95. Feature importance shows 'size' is the most predictive feature.",
    "next_stage": None,
})

MOCK_EXECUTION_RESULT: dict = {
    "stdout": "training complete",
    "figures": [],
    "error": None,
    "dataframe_changed": False,
}


# ── infer_problem_type ──────────────────────────────────────────────────────


def test_infer_problem_type_categorical_dtype():
    # Behavior 1: object dtype columns are always classification.
    # Why: categorical targets like "yes"/"no" or "cat"/"dog" are classification by definition.
    df = pd.DataFrame({"target": ["yes", "no", "yes", "no"]})
    assert infer_problem_type(df, "target") == "classification"


def test_infer_problem_type_numeric_many_unique():
    # Behavior 2: numeric columns with many unique values are regression.
    # Why: continuous numeric targets like price or temperature are regression problems.
    df = pd.DataFrame({"target": [1.1, 2.2, 3.3, 4.4, 5.5,
                                  6.6, 7.7, 8.8, 9.9, 10.0, 11.1]})
    assert infer_problem_type(df, "target") == "regression"


def test_infer_problem_type_numeric_few_unique():
    # Behavior 3: numeric columns with <= 10 unique values are classification.
    # Why: binary labels (0/1) and small ordinal categories (1-5 ratings) are classification.
    df = pd.DataFrame({"target": [0, 1, 0, 1, 0, 1, 0, 1]})
    assert infer_problem_type(df, "target") == "classification"


def test_infer_problem_type_boolean():
    # Behavior 4: boolean dtype columns are classification.
    # Why: True/False targets are binary classification.
    df = pd.DataFrame({"target": [True, False, True, False]})
    assert infer_problem_type(df, "target") == "classification"


def test_infer_problem_type_numeric_exactly_ten_unique():
    # Edge case: exactly 10 unique values is still classification (threshold is <=10).
    df = pd.DataFrame({"target": list(range(10)) * 3})
    assert infer_problem_type(df, "target") == "classification"


def test_infer_problem_type_numeric_eleven_unique():
    # Edge case: 11 unique values crosses the threshold into regression.
    df = pd.DataFrame({"target": list(range(11)) * 3})
    assert infer_problem_type(df, "target") == "regression"


# ── Prompt builders ─────────────────────────────────────────────────────────


def test_target_selection_prompt_includes_all_columns():
    # Behavior 5: the prompt lists every column so the user/LLM can pick a target.
    # Why: the LLM needs to know all available columns to make a recommendation.
    df = make_ml_df()
    prompt = build_target_selection_prompt(df)
    assert "price" in prompt
    assert "size" in prompt
    assert "color" in prompt
    assert "sold" in prompt


def test_target_selection_prompt_includes_dtypes():
    # Behavior 6: the prompt includes dtype information for each column.
    # Why: dtype helps the LLM distinguish categorical from numeric columns.
    df = make_ml_df()
    prompt = build_target_selection_prompt(df)
    assert "float" in prompt.lower() or "int" in prompt.lower()
    assert "object" in prompt.lower() or "string" in prompt.lower() or "categorical" in prompt.lower()


def test_target_selection_prompt_includes_sample_values():
    # Behavior 7: the prompt shows sample values so the LLM understands the data.
    # Why: sample values reveal patterns (e.g., binary 0/1 vs continuous float) that
    #      dtypes alone don't capture.
    df = make_ml_df()
    prompt = build_target_selection_prompt(df)
    # Should contain at least some actual data values
    assert "100" in prompt or "red" in prompt


def test_feature_selection_prompt_includes_non_target_columns():
    # Behavior 8: the feature prompt lists columns excluding the target.
    # Why: the target should not be a feature; listing only candidate features
    #      avoids confusion.
    df = make_ml_df()
    prompt = build_feature_selection_prompt(df, "price", "regression")
    assert "size" in prompt
    assert "color" in prompt
    assert "sold" in prompt


def test_feature_selection_prompt_includes_problem_type():
    # Behavior 9: the feature prompt mentions the problem type.
    # Why: problem type affects which features are useful (e.g., categorical features
    #      may need encoding for regression).
    df = make_ml_df()
    prompt = build_feature_selection_prompt(df, "price", "regression")
    assert "regression" in prompt.lower()


def test_preprocessing_prompt_includes_target_and_features():
    # Behavior 10: the preprocessing prompt mentions target and features by name.
    # Why: the LLM needs to know which columns to preprocess.
    df = make_ml_df()
    prompt = build_preprocessing_prompt(df, "price", ["size", "color"])
    assert "price" in prompt
    assert "size" in prompt
    assert "color" in prompt


def test_preprocessing_prompt_mentions_missing_values_when_present():
    # Behavior 11: the preprocessing prompt flags columns with missing values.
    # Why: missing values require specific handling (imputation, dropping) that the
    #      LLM must recommend.
    df = pd.DataFrame({
        "price": [100.0, None, 300.0],
        "size": [50, 60, 70],
        "color": ["red", "blue", None],
    })
    prompt = build_preprocessing_prompt(df, "price", ["size", "color"])
    assert "missing" in prompt.lower()


def test_model_selection_prompt_includes_problem_type():
    # Behavior 12: the model selection prompt mentions the problem type.
    # Why: classification and regression require different model families.
    prompt = build_model_selection_prompt("classification", (100, 5))
    assert "classification" in prompt.lower()


def test_model_selection_prompt_includes_dataset_shape():
    # Behavior 13: the model selection prompt mentions dataset dimensions.
    # Why: dataset size affects model choice (e.g., small datasets favor simpler models).
    prompt = build_model_selection_prompt("regression", (1000, 10))
    assert "1000" in prompt
    assert "10" in prompt


def test_training_prompt_includes_all_context():
    # Behavior 14: the training prompt includes target, features, model, and problem type.
    # Why: the LLM needs all of these to generate correct sklearn training code.
    prompt = build_training_prompt(
        "price", ["size", "color"], "random_forest", "regression",
    )
    assert "price" in prompt
    assert "size" in prompt
    assert "color" in prompt
    assert "random_forest" in prompt.lower() or "RandomForest" in prompt
    assert "regression" in prompt.lower()


def test_explanation_prompt_includes_training_result():
    # Behavior 15: the explanation prompt includes the training result for the LLM to interpret.
    # Why: the explanation stage summarizes the training outcome.
    training_result = "R-squared: 0.95\nMSE: 123.45"
    prompt = build_explanation_prompt(training_result)
    assert "0.95" in prompt
    assert "123.45" in prompt


# ── parse_ml_step_response ──────────────────────────────────────────────────


def test_parse_ml_step_response_extracts_fields():
    # Behavior 16: valid JSON with standard ML fields is extracted correctly.
    # Why: these structured fields drive session state updates and frontend rendering.
    raw = json.dumps({
        "explanation": "Use price as the target.",
        "target_column": "price",
        "next_stage": "features",
    })
    parsed = parse_ml_step_response(raw)
    assert parsed["explanation"] == "Use price as the target."
    assert parsed["target_column"] == "price"
    assert parsed["next_stage"] == "features"


def test_parse_ml_step_response_returns_error_for_malformed_json():
    # Behavior 17: non-JSON input returns a dict with an "error" key.
    # Why: graceful degradation instead of crashing.
    parsed = parse_ml_step_response("this is not json")
    assert "error" in parsed


def test_parse_ml_step_response_handles_code_fences():
    # Behavior 18: JSON wrapped in code fences is parsed correctly.
    # Why: LLMs non-deterministically wrap JSON in markdown fences.
    raw = '```json\n{"explanation": "fenced response", "next_stage": "features"}\n```'
    parsed = parse_ml_step_response(raw)
    assert parsed["explanation"] == "fenced response"


# ── Stage progression validation ────────────────────────────────────────────


def test_stage_progression_cannot_skip_stages():
    # Behavior 19: requesting "training" when ml_stage is "target" returns 400.
    # Why: each stage depends on the output of prior stages.
    session_id = create_ml_session()

    response = client.post("/api/ml-step", json={
        "session_id": session_id,
        "stage": "training",
        "user_input": "start training",
    })
    assert response.status_code == 400


def test_stage_progression_sequential_advancement():
    # Behavior 20: completing "target" allows requesting "features".
    # Why: validates that the state machine advances correctly.
    session_id = create_ml_session()

    with patch("main.call_llm_chat", return_value=MOCK_ML_TARGET_RESPONSE), \
         patch("main.execute_code", return_value=MOCK_EXECUTION_RESULT):
        response = client.post("/api/ml-step", json={
            "session_id": session_id,
            "stage": "target",
            "user_input": "I want to predict price",
        })
    assert response.status_code == 200

    # Now "features" should be allowed
    with patch("main.call_llm_chat", return_value=MOCK_ML_FEATURE_RESPONSE), \
         patch("main.execute_code", return_value=MOCK_EXECUTION_RESULT):
        response = client.post("/api/ml-step", json={
            "session_id": session_id,
            "stage": "features",
            "user_input": "Use size and color",
        })
    assert response.status_code == 200


def test_stage_restart_resets_subsequent_state():
    # Behavior 21: going back to "target" from "model" resets features, problem type, etc.
    # Why: changing the target invalidates all subsequent choices.
    session_id = create_ml_session()
    session = session_store.get(session_id)

    # Manually set state as if we've progressed to "model"
    session.ml_stage = "model"
    session.ml_target_column = "price"
    session.ml_features = ["size", "color"]
    session.ml_problem_type = "regression"
    session.ml_model_choice = None

    # Restart from "target"
    with patch("main.call_llm_chat", return_value=MOCK_ML_TARGET_RESPONSE), \
         patch("main.execute_code", return_value=MOCK_EXECUTION_RESULT):
        response = client.post("/api/ml-step", json={
            "session_id": session_id,
            "stage": "target",
            "user_input": "Actually, predict sold instead",
        })
    assert response.status_code == 200

    # Features and model_choice from the prior run should be reset.
    # problem_type is re-inferred for the new target, so it won't be None
    # (it gets set during _update_ml_session_state for the "target" stage).
    session = session_store.get(session_id)
    assert session.ml_features is None
    assert session.ml_model_choice is None
    # The stage should now be "target" (restarted)
    assert session.ml_stage == "target"


def test_stage_progression_first_stage_must_be_target():
    # Behavior 22: the first ML step must be "target" — can't start at "features".
    # Why: you must select a target before selecting features.
    session_id = create_ml_session()

    response = client.post("/api/ml-step", json={
        "session_id": session_id,
        "stage": "features",
        "user_input": "Use size and color",
    })
    assert response.status_code == 400


# ── /api/ml-step endpoint ──────────────────────────────────────────────────


def test_ml_step_endpoint_returns_sse_stream_with_explanation():
    # Behavior 23: the SSE stream contains an explanation event.
    # Why: the explanation is the primary user-facing output for each ML stage.
    session_id = create_ml_session()

    with patch("main.call_llm_chat", return_value=MOCK_ML_TARGET_RESPONSE), \
         patch("main.execute_code", return_value=MOCK_EXECUTION_RESULT):
        response = client.post("/api/ml-step", json={
            "session_id": session_id,
            "stage": "target",
            "user_input": "I want to predict price",
        })

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    events = parse_sse_events(response.text)
    explanation_events = [e for e in events if e["event"] == "explanation"]
    assert len(explanation_events) >= 1
    assert "price" in explanation_events[0]["data"].lower()


def test_ml_step_endpoint_returns_404_for_unknown_session():
    # Behavior 24: unknown session_id returns 404.
    # Why: a clear 404 tells the frontend the session expired.
    response = client.post("/api/ml-step", json={
        "session_id": "nonexistent-session-id",
        "stage": "target",
        "user_input": "predict price",
    })
    assert response.status_code == 404


def test_ml_step_endpoint_returns_400_for_invalid_stage_progression():
    # Behavior 25: requesting an invalid stage transition returns 400.
    # Why: prevents corrupted ML state from incomplete workflows.
    session_id = create_ml_session()

    response = client.post("/api/ml-step", json={
        "session_id": session_id,
        "stage": "model",
        "user_input": "use random forest",
    })
    assert response.status_code == 400


def test_ml_step_endpoint_updates_session_ml_state():
    # Behavior 26: after the target stage, session stores the target column and problem type.
    # Why: subsequent stages need target column and problem type from session state.
    session_id = create_ml_session()

    with patch("main.call_llm_chat", return_value=MOCK_ML_TARGET_RESPONSE), \
         patch("main.execute_code", return_value=MOCK_EXECUTION_RESULT):
        client.post("/api/ml-step", json={
            "session_id": session_id,
            "stage": "target",
            "user_input": "I want to predict price",
        })

    session = session_store.get(session_id)
    assert session.ml_stage == "target"
    assert session.ml_target_column == "price"
    assert session.ml_problem_type is not None


def test_ml_step_training_stage_executes_code():
    # Behavior 27: the training stage runs generated code through the executor.
    # Why: training actually fits a model; the code must be executed to produce results.
    session_id = create_ml_session()
    session = session_store.get(session_id)

    # Set up state as if we've completed stages up to training
    session.ml_stage = "model"
    session.ml_target_column = "price"
    session.ml_features = ["size", "color"]
    session.ml_problem_type = "regression"
    session.ml_model_choice = "random_forest"

    with patch("main.call_llm_chat", return_value=MOCK_ML_TRAINING_RESPONSE), \
         patch("main.execute_code", return_value=MOCK_EXECUTION_RESULT) as mock_exec:
        response = client.post("/api/ml-step", json={
            "session_id": session_id,
            "stage": "training",
            "user_input": "Train the model",
        })

    assert response.status_code == 200
    events = parse_sse_events(response.text)

    # Verify code was executed
    mock_exec.assert_called_once()

    # Verify result event was emitted
    result_events = [e for e in events if e["event"] == "result"]
    assert len(result_events) == 1
