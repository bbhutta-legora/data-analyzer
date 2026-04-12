# Step 14 Execution Plan: Export

## 1. What we're building

Step 14 adds Jupyter notebook export to the Smart Dataset Explainer. The user can download their entire analysis session as a `.ipynb` file at any point during the chat. The notebook includes a header cell with library imports, a data-loading cell, and for each analysis turn a markdown cell with the plain-English explanation followed by a code cell with the generated code. The backend builds the notebook JSON from the session's `code_history` and returns it as a binary download. The frontend adds a download button to the chat UI. (PRD #7 / G5; Implementation plan Step 14)

## 2. Current state

Verified by reading actual files in the repository:

### Backend

- **`backend/session.py` (lines 26-53):** `Session` dataclass already stores `code_history: list` (line 46). Each entry is a dict with `code`, `explanation`, and `result` keys (populated at `main.py` lines 453-460). The `result` sub-dict contains `stdout` (str) and `figures` (list of base64 strings). This is the data source for the notebook.

- **`backend/main.py` (lines 1-470):** Currently has five routes: `/api/health` (GET, line 191), `/api/models` (GET, line 196), `/api/validate-key` (POST, line 212), `/api/upload` (POST, line 260), `/api/chat` (POST, line 360). The file header comment (line 13) already lists `Step 14: /api/export` as a planned route. No `/api/export` route exists yet. No `/api/clean` route exists yet either (Step 10 is in progress on a separate branch).

- **`backend/exporter.py`:** Does **not exist** yet. Listed in `architecture.md` module structure (line 44) and described at line 81: "Builds a Jupyter notebook (.ipynb JSON) from the session's code history."

- **`backend/requirements.txt` (lines 1-14):** Does **not** include `nbformat`. The implementation plan's test code and `build_notebook()` function build the `.ipynb` JSON dict manually (no library dependency), so `nbformat` is likely unnecessary.

- **`backend/sandbox_libraries.py` (lines 1-33):** Lists `pd`, `np`, `plt`, `sns`, `sklearn` as the sandbox libraries. The exported notebook's header cell should mirror these imports.

- **`backend/tests/`:** Contains 8 test files. No `test_exporter.py` exists yet.

### Frontend

- **`frontend/src/api.ts` (line 11):** Comment already lists `Step 14: exportNotebook()` as planned. The function does not exist yet. Current functions: `validateApiKey`, `uploadFile`, `sendChatMessage`, `fetchAvailableModels`.

- **`frontend/src/components/ChatPanel.tsx` (lines 1-154):** Renders `DataSummary` at the top, a scrollable message list, and a fixed input bar at the bottom. There is no header bar or toolbar area — the component is a flex column of (scroll area, input bar). An export button needs to be added somewhere.

- **`frontend/src/store.ts` (lines 1-118):** `AppState` has `sessionId` (needed to construct the export URL). No export-related state exists, and none is likely needed — a direct download doesn't require store changes.

- **`frontend/src/App.tsx` (lines 1-30):** Renders `CurrentScreen` + `HelpModal`. The `HelpModal` is rendered as an overlay at the app level.

### Architecture

- **`planning/architecture.md` (line 172):** Communication protocol table specifies `GET /api/export/{session_id}` returning `.ipynb` file download. Content type should be `application/x-ipynb+json`.

- **`planning/architecture.md` (line 81):** `exporter.py` module description: "Builds a Jupyter notebook (.ipynb JSON) from the session's code history. Each entry becomes a code cell + a markdown cell (for the explanation). Adds a header cell with import statements and a cell that loads the dataset. The exported notebook is self-contained and runnable."

## 3. Execution sequence

| Phase | Name | What happens |
|-------|------|-------------|
| A0 | Wireframes | Present 2-3 markdown wireframe options for the export button placement in ChatPanel. The button is a small addition, but its placement affects the chat UI layout (e.g., header bar vs. floating button vs. inline with input). Wait for user confirmation. |
| A | Test spec | Present behaviors and test cases for `exporter.py` (unit tests for notebook structure) and the `/api/export/{session_id}` route (integration test). Wait for confirmation. |
| B | Tests | Write `backend/tests/test_exporter.py` and export route tests. Run them and confirm all fail for the right reasons (ImportError / 404 since the module and route don't exist). |
| C | Implementation | Create `backend/exporter.py` with `build_notebook()`. Add `/api/export/{session_id}` route to `main.py`. Add `exportNotebook()` to `frontend/src/api.ts`. Add export button to `ChatPanel.tsx`. |
| D | Verification | Run all tests, confirm they pass. Break-the-implementation check: intentionally break the notebook cell generation (e.g., skip markdown cells) and verify the relevant test fails. Self-audit summary. Present for user confirmation. |
| E | Code review | Scan all changed files against `harness/code_review_patterns.md`. Fix violations, re-run tests. |
| F | Reflection | Capture learnings, propose harness updates if warranted. |

## 4. Implementation approach

### Files to create

- **`backend/exporter.py`** — New module. Single public function: `build_notebook(code_history: list[dict], filename: str) -> dict`. Returns a Python dict representing a valid nbformat v4 notebook JSON structure. No external dependencies (builds the dict manually, no `nbformat` library needed).

- **`backend/tests/test_exporter.py`** — Unit tests for `build_notebook()`.

### Files to modify

- **`backend/main.py`** — Add `GET /api/export/{session_id}` route. Looks up session via `session_store.get()`, calls `build_notebook(session.code_history, ...)`, returns the notebook as a `StreamingResponse` or `Response` with `media_type="application/x-ipynb+json"` and a `Content-Disposition: attachment; filename="analysis.ipynb"` header.

- **`frontend/src/api.ts`** — Add `exportNotebook(sessionId: string)` function. This will trigger a browser download by opening `window.location` or creating a temporary `<a>` element pointing to `/api/export/{sessionId}`. Since the endpoint is a GET returning a file, no fetch + JSON parsing is needed — a direct navigation/link approach is simpler and handles the download natively.

- **`frontend/src/components/ChatPanel.tsx`** — Add an "Export Notebook" button. Placement TBD (see wireframe phase), but likely in a small header/toolbar area above the message list.

### Function decomposition (backend/exporter.py)

Pure logic — no I/O, no side effects:

1. `build_notebook(code_history, filename) -> dict` — Top-level public function. Assembles cells and wraps them in the notebook structure.
2. `_make_code_cell(source: str) -> dict` — Creates a single nbformat v4 code cell dict.
3. `_make_markdown_cell(source: str) -> dict` — Creates a single nbformat v4 markdown cell dict.
4. `_make_header_cell() -> dict` — Returns the imports code cell (pandas, numpy, matplotlib, seaborn, sklearn).
5. `_make_data_loading_cell(filename: str) -> dict` — Returns a code cell that loads the dataset (e.g., `df = pd.read_csv("filename")`).
6. `_notebook_wrapper(cells: list[dict]) -> dict` — Wraps a list of cells in the top-level nbformat v4 structure (`nbformat`, `nbformat_minor`, `metadata`, `cells`).

### Key design decisions

1. **No `nbformat` dependency.** The `.ipynb` format is just JSON with a well-defined schema. Building the dict manually avoids adding a dependency and keeps the module simple. The implementation plan's test code also assumes a plain dict approach (`notebook["cells"]`, `notebook["nbformat"]`).

2. **GET endpoint with session_id in path.** Matches architecture.md spec: `GET /api/export/{session_id}`. The response is a file download (binary response with appropriate headers), not a JSON response.

3. **Direct browser download (no two-step flow).** The frontend triggers the download by navigating to the GET URL (e.g., `window.open("/api/export/{sessionId}")`). No need for a generate-then-download pattern since the notebook is built synchronously from in-memory data.

4. **Filename parameter from session.** The `build_notebook()` function takes a `filename` parameter for the data-loading cell. This needs to come from the session. Currently, `Session` does not store the original filename. The session stores DataFrames keyed by stem name (e.g., `"sales"` for `sales.csv`). We can either: (a) add an `original_filename` field to `Session`, or (b) derive it from the first DataFrame key + assume `.csv`. **Decision needed from user** — see Section 5.

5. **Initial summary inclusion.** The PRD says the notebook should include "all generated code in executable cells, outputs and charts as cell outputs, plain-English explanations as markdown cells." The initial summary (from upload) is stored differently from chat turns — it's in the upload response, not in `code_history`. **Decision needed from user** — should the summary be a markdown cell in the notebook?

6. **Figure embedding.** The `code_history` entries include `result.figures` (base64 PNG strings). The implementation plan's `build_notebook()` signature only takes `code_history` and `filename`. Including figures as cell outputs would make the notebook more complete but adds complexity (base64 images need to be embedded as cell output display_data). **Decision needed from user** — embed figures or just include the code that generates them?

## 5. Deviations from the implementation plan

1. **`build_notebook` signature may need expansion.** The implementation plan specifies `build_notebook(code_history, filename)`. If we decide to include the initial summary, we'll need an additional parameter (e.g., `summary_text: str | None`). If we embed figures, the `code_history` entries already contain `result.figures`, so no signature change is needed, but the cell-building logic becomes more complex.

2. **Original filename not stored in Session.** The plan's `build_notebook()` takes a `filename` parameter (e.g., `"data.csv"`) for the data-loading cell. But `Session` doesn't store the original filename — only DataFrame keys (stems without extension). We'll need to either:
   - Add `original_filename: str` to the `Session` dataclass and populate it during `session_store.create()` (requires modifying `session.py` and `main.py`'s upload route), or
   - Use the DataFrame key + `.csv` as a reasonable default, with a comment in the notebook that the user should update the path.

   The first approach is cleaner and more correct. This is a minor deviation — the plan doesn't mention it because it assumes the filename is readily available.

3. **Function decomposition is more granular than the plan.** The plan describes `exporter.py` as implementing a single `build_notebook()` function. The execution plan breaks it into helper functions (`_make_code_cell`, `_make_markdown_cell`, etc.) following the project's coding principle of separating pure logic into small, testable units.

4. **Frontend `api.ts` function may use direct navigation instead of `apiFetch`.** The plan says to add `exportNotebook()` to `api.ts`. Since the endpoint returns a file (not JSON), using `apiFetch` (which calls `response.json()`) would fail. A direct `window.open()` or `<a>` download approach is more appropriate.

5. **No store changes needed.** The plan doesn't mention store changes, and none are needed. The export button reads `sessionId` from the store and triggers a navigation — no new state required.

---

## Resolved decisions

1. **Export button placement** — Deferred to Phase A0 wireframes.

2. **No initial summary in notebook** — The notebook contains only the code_history entries (code cells + explanation markdown cells), not the upload-time summary.

3. **Code-only, no embedded figures** — The notebook includes the code that generates figures. Figures regenerate when the notebook is run. Keeps the file small and truly self-contained.

4. **Manual dict, no `nbformat` dependency** — The `.ipynb` format is simple enough to build as a plain dict. No new dependency needed.

5. **Download filename derived from uploaded file** — e.g., `sales_analysis.ipynb` from `sales.csv`. Requires storing the original filename on the session.

6. **Add `original_filename: str` to Session** — Needed for both the data-loading cell and the download filename. Small modifications to `session.py` and `main.py`'s upload route.
