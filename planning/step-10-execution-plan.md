# Step 10 — Data Cleaning: Execution Plan

## What we're building

Step 10 adds interactive data cleaning with confirm-before-apply suggestions (PRD #4). Cleaning suggestions appear after upload (in DataSummary) and during chat Q&A (in assistant messages). Each suggestion has option buttons (e.g., "Drop rows" / "Fill with median"). Clicking an option calls a new `/api/clean` POST endpoint that applies the action to the session's working DataFrame and returns updated dataset stats. No LLM follow-up call — the user can ask about data quality in the chat if they want more suggestions.

## Current state

Relevant code already in place:

- **`backend/session.py:26-63`** — `Session` dataclass stores `dataframes: dict[str, pd.DataFrame]` (working copies) and `dataframes_original: dict[str, pd.DataFrame]` (immutable snapshots for reset). The exec namespace binds `dfs` to the working copies dict.
- **`backend/session.py:76`** — `SessionStore.create()` accepts `dict[str, pd.DataFrame]`, not a single DataFrame.
- **`backend/main.py:12`** — Route comment already reserves `/api/clean` for Step 10.
- **`backend/main.py:360-464`** — `/api/chat` endpoint demonstrates SSE pattern, session lookup, LLM call, and error handling.
- **`backend/llm.py:101-105, 158-160`** — Both summary and chat system prompts already ask the LLM for `cleaning_suggestions` with `{description, options}` shape.
- **`frontend/src/store.ts:30-33`** — `CleaningSuggestion` type: `{description: string, options: string[]}`.
- **`frontend/src/store.ts:57`** — `Message` type already has optional `cleaningSuggestions` field.
- **`frontend/src/components/DataSummary.tsx:37-75`** — `CleaningSuggestionCard` renders description + option buttons, but buttons have no `onClick` handler (marked `REVIEW: Step 10`).
- **`frontend/src/components/DataSummary.tsx:204-212`** — Upload-time suggestions are rendered in the summary panel.
- **`frontend/src/components/ChatPanel.tsx:138-139`** — Chat SSE handler stores `cleaningSuggestions` on assistant messages.
- **`frontend/src/components/MessageBubble.tsx`** — Does NOT render `cleaningSuggestions` from messages yet.

## Execution sequence

| Phase | Name | What happens |
|-------|------|-------------|
| A0 | Wireframes | Present 2-3 markdown wireframe options showing: (1) how cleaning option buttons look before/during/after an action, (2) where updated stats appear, (3) how follow-up suggestions render. Cover both DataSummary and chat message contexts. Wait for user pick. |
| A | Test spec | Present behaviors and test cases for backend `/api/clean` endpoint and frontend cleaning interaction. Wait for user confirmation. |
| B | Tests | Write `backend/tests/test_clean.py` and `frontend/src/__tests__/CleaningPrompt.test.tsx` (or equivalent). Run them, confirm all fail for the right reasons. |
| C | Implementation | Build backend endpoint + frontend wiring to make tests pass. |
| D | Verification | Break-the-implementation check + self-audit. Present for user confirmation. |
| E | Code review | Scan changed files against `harness/code_review_patterns.md`. Fix violations, re-run tests. |
| F | Reflection | Capture learnings, propose harness updates if warranted. |

## Implementation approach

### Backend

**Modify `backend/main.py`:**
- Add Pydantic `CleanRequest` model: `session_id: str`, `action: str`, `column: str | None = None`, `dataset_name: str | None = None`.
- Add `POST /api/clean` route that:
  1. Looks up session (404 if missing).
  2. Resolves target DataFrame from `session.dataframes` (see "Decisions" below).
  3. Dispatches to a pure cleaning function based on `action`.
  4. Updates `session.dataframes[name]` in place (the exec namespace `dfs` dict already references the same dict object).
  5. Returns JSON: `{row_count, column_count, columns, dtypes, missing_values, cleaning_suggestions?, message}`.

**Create `backend/clean.py`** (pure logic, no I/O):
- `apply_cleaning_action(df, action, column) -> pd.DataFrame` — dispatches to action handlers.
- Individual pure functions: `drop_duplicates(df)`, `fill_median(df, column)`, `drop_missing_rows(df, column)`.
- `VALID_ACTIONS` constant for validation.

**Create `backend/tests/test_clean.py`:**
- Tests per the implementation plan, adapted for `dict[str, pd.DataFrame]` signature.

### Frontend

**Modify `frontend/src/components/DataSummary.tsx`:**
- Wire `onClick` on `CleaningSuggestionCard` option buttons to call `/api/clean`.
- Add loading/success/error states to the card.
- On success, update `datasetInfo` in the store with new stats.
- Render follow-up suggestions if returned.

**Modify `frontend/src/components/MessageBubble.tsx`:**
- Render `cleaningSuggestions` from assistant messages using the same `CleaningSuggestionCard` component (extract it to a shared location or import from DataSummary).

**Modify `frontend/src/store.ts`:**
- Add `updateDatasetMetadata` action to update a single dataset's metadata after cleaning.
- Add `cleaningInProgress: boolean` state (or handle locally in component).

**Modify `frontend/src/api.ts`:**
- Add `applyCleaningAction(sessionId, action, column?, datasetName?)` function.

### Key design decisions

1. **Extract `CleaningSuggestionCard` to shared component** — Currently lives inside `DataSummary.tsx` but needs reuse in `MessageBubble.tsx`. Move to `frontend/src/components/CleaningSuggestionCard.tsx`.
2. **Pure cleaning logic in `clean.py`** — Separates I/O (route handler) from logic (DataFrame mutations) per coding principles.
3. **JSON response, not SSE** — Cleaning is a synchronous, fast operation (drop rows, fill values). No streaming needed. No LLM follow-up call — return updated stats only.
4. **`dataset_name` parameter** — Added to `CleaningSuggestion` type so the LLM specifies which DataFrame a suggestion refers to. Required in the `/api/clean` request body.

## Deviations from the implementation plan

1. **`session_store.create(df)` with single DataFrame**: The plan's test code passes a bare `pd.DataFrame` to `session_store.create()`, but the actual signature is `create(dataframes: dict[str, pd.DataFrame])`. All tests must use `session_store.create({"data": df})` and access `session.dataframes["data"]` instead of `session.dataframe`.

2. **`session.dataframe` (singular) does not exist**: The plan references `session.dataframe` but the `Session` dataclass only has `session.dataframes` (plural, a dict). Tests and implementation must use `session.dataframes[name]`.

3. **No `CleaningPrompt.tsx` needed**: The plan proposes creating a new `CleaningPrompt.tsx` component, but `CleaningSuggestionCard` already exists in `DataSummary.tsx`. We should extract and extend it rather than create a parallel component.

4. **Multi-DataFrame support**: The plan assumes a single dataframe per session. The codebase supports multiple DataFrames (`dict[str, pd.DataFrame]`). The `/api/clean` request must include a `dataset_name` field to identify the target.

5. **Follow-up LLM call complexity**: The plan says "optionally calls the LLM to check for follow-up cleaning suggestions." This adds latency and requires API key availability. Recommend making this optional (skip in v1, or make it a separate subsequent call) to keep the cleaning action fast and testable without LLM mocking.

## Resolved decisions

1. **Multi-DataFrame targeting** — Add `dataset_name` field to `CleaningSuggestion` type. The LLM prompt will be updated to include the dataset name in each suggestion. Frontend passes it through to `/api/clean`.

2. **One-click confirmation** — Clicking the option button directly applies the action. No separate confirmation dialog.

3. **No LLM follow-up** — `/api/clean` returns updated stats only. No LLM call for follow-up suggestions. The user can ask about data quality in the chat.

4. **Include undo/reset** — Add a "Reset to original" button since the `dataframes_original` infrastructure already exists in `session.py`.
