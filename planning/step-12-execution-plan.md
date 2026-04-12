# Step 12 Execution Plan — Guided ML Backend

## What we're building

Step 12 adds the backend prompt chains and endpoint logic for a guided ML workflow (PRD capability #5). The system walks users through a multi-step process — target selection, feature selection, preprocessing, model selection, training/evaluation, and explanation — where each step produces a tailored LLM prompt and parses a structured response. This is backend-only; the frontend (Step 13) will consume these endpoints later.

## Current state

Relevant existing infrastructure:

- **`backend/llm.py:150-206`** — Chat prompt construction pattern (`build_chat_system_prompt`, `_CHAT_RESPONSE_FORMAT_INSTRUCTIONS`). ML prompts will follow the same pattern: pure `build_*` functions + format instructions + `parse_*` response parsers.
- **`backend/llm.py:389-412`** — `call_llm_chat()` dispatches to OpenAI/Anthropic. ML workflow will reuse this directly — no new LLM call infrastructure needed.
- **`backend/main.py:360-439`** — `/api/chat` SSE endpoint. Shows the session lookup + prompt build + LLM call + code execution + SSE streaming pattern. ML endpoint will follow the same structure.
- **`backend/session.py:26-53`** — `Session` dataclass. Currently has `conversation_history`, `code_history`, `dataframes`, `exec_namespace`. No ML workflow state yet — needs new fields for tracking ML progress (current stage, target column, selected features, problem type, trained model reference).
- **`backend/sandbox_libraries.py:13-23`** — `sklearn` is already in the sandbox namespace, so LLM-generated training code can use it directly.
- **`backend/executor.py`** — Sandboxed code execution. ML training code will run through the same executor.

## Execution sequence

### Phase A — Test spec

Present ML workflow behaviors and test cases for user review. Key behavior groups:
1. Pure functions: `infer_problem_type`, `build_target_selection_prompt`, `build_feature_selection_prompt`, `build_model_selection_prompt`, `build_training_prompt`, `parse_ml_step_response`
2. ML session state management (stage tracking, field persistence)
3. Endpoint integration: `/api/ml-step` request/response cycle

### Phase B — Tests

Write `backend/tests/test_ml_workflow.py` with tests covering all behaviors from Phase A. Run and confirm they fail for the right reasons (missing functions/endpoint).

### Phase C — Implementation

1. Add ML workflow state fields to `Session` dataclass
2. Add pure prompt builders and parsers to `llm.py`
3. Add `/api/ml-step` endpoint to `main.py`
4. Wire up code execution for the training stage

### Phase D — Verification

Break-the-implementation checks on key invariants:
- `infer_problem_type` correctly distinguishes classification vs. regression
- Stage progression prevents skipping steps
- Training prompt generates executable sklearn code

### Phase E — Code review

Scan all changed files against `harness/code_review_patterns.md`.

### Phase F — Reflection

Capture learnings, update architecture docs.

## Implementation approach

### New files
- `backend/tests/test_ml_workflow.py` — all ML workflow tests

### Modified files

**`backend/session.py`** — Add ML workflow state fields to `Session`:
```
ml_stage: Optional[str] = None          # current stage: target, features, preprocessing, model, training, explanation, None
ml_target_column: Optional[str] = None   # user-confirmed target column
ml_features: Optional[list[str]] = None  # user-confirmed feature columns
ml_problem_type: Optional[str] = None    # "classification" or "regression"
ml_model_choice: Optional[str] = None    # e.g. "random_forest", "logistic_regression"
```

**`backend/llm.py`** — Add pure functions (no I/O, trivially testable):
- `infer_problem_type(df, target_column) -> str` — returns "classification" or "regression" based on dtype and unique-value count
- `build_target_selection_prompt(df) -> str` — lists columns with dtypes and sample values
- `build_feature_selection_prompt(df, target_column) -> str` — includes correlation data, suggests features
- `build_preprocessing_prompt(df, target_column, features) -> str` — identifies encoding/scaling/missing-value needs
- `build_model_selection_prompt(df, target_column, features) -> str` — suggests models based on problem type
- `build_training_prompt(df, target_column, features, model_choice, problem_type) -> str` — generates sklearn training code request
- `parse_ml_step_response(raw_response) -> dict` — extracts structured fields from LLM response

Each prompt builder produces a JSON response format instruction specific to that stage.

**`backend/main.py`** — Add `/api/ml-step` POST endpoint:
- Request body: `{ session_id, stage, user_input }` where `stage` is the ML step and `user_input` is the user's selection/confirmation
- Uses SSE streaming (same pattern as `/api/chat`)
- Routes to the appropriate prompt builder based on `stage`
- Updates session ML state after each successful step
- Returns explanation + any generated code results + next stage indicator

### Design decisions

**Separate `/api/ml-step` endpoint rather than extending `/api/chat`:**
The ML workflow has distinct stage-based routing, session state mutations, and response formats. Overloading `/api/chat` with ML-specific branching would violate single-responsibility and make both flows harder to test. The frontend (Step 13) will also need to render ML-specific UI per stage, so a dedicated endpoint with stage-aware responses is cleaner.

**ML stage as explicit state machine:**
Session tracks `ml_stage` as one of: `None | "target" | "features" | "preprocessing" | "model" | "training" | "explanation"`. Each stage transition is validated — you can't jump to "training" without completing "target" through "model". The user can restart the workflow at any time by sending `stage: "target"`.

**Problem type inference is a pure function, not an LLM call:**
`infer_problem_type` uses simple heuristics (categorical dtype = classification; numeric with <= 10 unique values = classification; otherwise regression). This avoids an unnecessary LLM round-trip and is deterministic/testable. The LLM is told the problem type in subsequent prompts.

**ML conversation history kept in main conversation_history:**
ML workflow messages are appended to the existing `conversation_history` list so the LLM has full context. A `ml_stage` field on session (not on messages) tracks workflow progress separately.

## Deviations from the implementation plan

1. **Adding `build_preprocessing_prompt` and `build_training_prompt`** — The implementation plan's test sketch only lists `build_target_selection_prompt`, `build_feature_selection_prompt`, and `build_model_selection_prompt`. The PRD defines 6 stages (target, features, preprocessing, model, training, explanation), so we need prompt builders for all of them. Preprocessing and training prompts are the most important for generating executable code.

2. **Explicit ML state fields on Session** — The implementation plan doesn't specify how ML workflow state is tracked. We add typed fields (`ml_stage`, `ml_target_column`, `ml_features`, `ml_problem_type`, `ml_model_choice`) rather than a generic dict, for type safety and clarity.

3. **`/api/ml-step` as a dedicated endpoint** — The implementation plan suggests "add `/api/ml-step` endpoint or extend `/api/chat`". We choose the dedicated endpoint for separation of concerns.

## Resolved decisions

1. **Separate `/api/ml-step` endpoint** — dedicated endpoint, not extending `/api/chat`. Cleaner stage-based routing and testing.

2. **All 6 ML stages in MVP** — target selection, feature selection, preprocessing, model selection, training/evaluation, explanation. Full PRD scope.

3. **Strict stage progression with restart** — can't skip stages, but can restart from any earlier stage (resets subsequent state).

4. **Classification threshold: <= 10 unique values** — numeric columns with 10 or fewer unique values treated as classification. Covers binary labels and small ordinal categories.

5. **Single-DataFrame for MVP** — default to first/only DataFrame. Multi-DataFrame ML deferred.
