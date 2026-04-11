# Smart Dataset Explainer — PRD

## 1. Problem

Junior and aspiring data scientists frequently struggle with the first steps of working with a new dataset. They know they should do exploratory data analysis, clean their data, and eventually build models — but they lack the experience to know *what* to look for, *what questions* to ask, and *how* to write the code that gets them there.

Existing tools either assume expertise (pandas profiling, raw Jupyter notebooks) or hide everything behind a black box (no-code AutoML platforms). Neither teaches the user anything.

**This tool fills the gap:** an AI-powered conversational data analyst that helps junior data scientists explore, clean, understand, and model their data — while showing them the code and reasoning behind every step.

## 2. Goals

- **G1:** Enable a user to upload a tabular dataset and immediately understand its structure, quality, and key characteristics — without writing any code.
- **G2:** Let the user ask free-text questions about their data and receive answers grounded in real analysis (generated code, executed results, plain-English explanations).
- **G3:** Guide the user through data cleaning with transparent, confirm-before-applying suggestions.
- **G4:** Walk the user through an end-to-end ML workflow (target selection, feature selection, preprocessing, model training, evaluation) with explanations at each step.
- **G5:** Produce a downloadable Jupyter Notebook of the full session so the user walks away with reusable, runnable code.

## 3. Non-Goals

- **Real-time or streaming data.** The tool accepts static file uploads only.
- **Multi-dataset joins.** One dataset per session.
- **Collaboration or sharing.** No user accounts, no shared sessions.
- **Data storage or warehousing.** Sessions are ephemeral; no data persists after the tab is closed.
- **Production-grade security or compliance.** This is a portfolio project, not enterprise software.

## 4. Target User

Junior or aspiring data scientists — people learning data analysis who have basic Python familiarity but limited hands-on experience with EDA, data cleaning, and modeling workflows. They want to *learn by doing* with guidance, not just receive answers.

## 5. User Experience

### 5.1 API Key Setup

The user provides their own LLM API key (BYOK) before using the tool. This is a one-time setup step per session, presented as a simple input field.

### 5.2 Upload

The user uploads a CSV or Excel file (`.csv`, `.xlsx`, `.xls`). For multi-sheet Excel files, the user selects which sheet to analyze.

### 5.3 Initial Summary

On upload, the system automatically provides:

- Row and column count
- Column names and inferred types
- Data quality issues detected (missing values, duplicates, type inconsistencies, outliers) — each presented as a clickable cleaning suggestion with options (e.g. "I found 47 duplicate rows — Remove / Keep")
- 3–5 suggested questions tailored to the specific dataset (e.g. "What is the distribution of age?" or "Are there correlations between price and rating?")

Both suggested questions and cleaning suggestions are clickable, allowing the user to start exploring or cleaning immediately.

### 5.4 Conversational Analysis

The user asks free-text questions about their data. For each question, the system:

1. Generates Python code (pandas, matplotlib, seaborn, etc.) to answer it
2. Executes the code in a sandboxed environment
3. Returns the results — charts, tables, statistics — with a plain-English explanation
4. Hides the generated code by default behind a "Show code" toggle, so the user can optionally inspect and learn from it

The conversation is stateful within the session — the system remembers previous questions and transformations.

### 5.5 Data Cleaning

The system proactively surfaces cleaning suggestions throughout the session — not just once at upload. Suggestions appear:

- **After upload**, as part of the initial summary (see 5.3)
- **During analysis**, when the system notices an issue relevant to the user's question (e.g. "Before I can calculate the average revenue, I should flag that this column has 8% missing values — how would you like to handle them?")
- **After a cleaning action**, if resolving one issue reveals or affects another (e.g. "Now that duplicates are removed, here's an updated look at the missing value counts — column 'age' still has 12% missing.")

Each suggestion includes options for the user to choose from:

- "I found 47 duplicate rows — Remove / Keep"
- "Column 'revenue' has 8% missing values — Drop rows / Fill with median / Fill with zero / Leave as-is"
- "Column 'signup_date' has inconsistent date formats — Standardize to YYYY-MM-DD / Leave as-is"

Each fix requires explicit user confirmation before being applied. The analysis then continues on the cleaned data. This teaches the user that data cleaning is iterative, contextual, and decision-driven — not a one-time step.

### 5.6 Guided ML Workflow

When the user wants to build a predictive model, the system walks through a step-by-step workflow:

1. **Target selection** — "Which column do you want to predict?"
2. **Feature selection** — "Here are the available features. I'd suggest these based on correlation — do you agree?"
3. **Preprocessing** — Handle encoding, scaling, and missing values with explanations
4. **Model selection** — Suggest appropriate model(s) based on the problem type, with brief explanations of each
5. **Training and evaluation** — Train the model, present metrics (accuracy, R², confusion matrix, etc.) with plain-English interpretation
6. **Explanation** — Summarize what the model learned and any caveats

Each step waits for user input or confirmation before proceeding.

### 5.7 Error Handling

When generated code fails to execute, the system:

1. Shows the error to the user with a plain-English explanation of what went wrong
2. Automatically re-prompts the LLM with the error context and retries
3. If the retry also fails, displays a friendly message suggesting the user rephrase their question

### 5.8 Export

At any point, the user can download the full session as a Jupyter Notebook (`.ipynb`). The notebook includes:

- All generated code in executable cells
- Outputs and charts as cell outputs
- Plain-English explanations as markdown cells

The exported notebook is self-contained and runnable.

## 6. Architecture Constraints

- **Client + backend architecture.** A frontend handles the UI and chat experience; a Python backend manages LLM interaction, code generation, and sandboxed execution.
- **Code execution must be sandboxed.** Generated code runs in an isolated environment with resource limits. The sandbox must prevent filesystem access, network calls, or other side effects beyond the dataset in memory.
- **BYOK model.** The backend proxies LLM calls using the user's API key. No keys are stored server-side beyond the session lifetime.

## 7. Assumptions

- The user has access to an LLM API key (e.g. OpenAI, Anthropic).
- Datasets are small-to-medium tabular data (reasonable for in-memory pandas processing) Give the user a range of file sizes they can use.
- The LLM can generate correct Python code for common EDA and ML tasks the majority of the time, with self-correction handling the remaining cases.

## 8. Risks and Open Questions

| Risk | Impact | Mitigation |
|------|--------|------------|
| LLM generates incorrect or misleading analysis | User learns wrong conclusions | Show code for transparency; include caveats in explanations |
| Code generation failures are frequent | Poor UX, user loses trust | Auto-retry with error context; test with common dataset types |
| Sandbox escape | Security vulnerability | Use process-level isolation with strict resource limits |
| BYOK friction deters users from trying the tool | Reduces portfolio impact | Include a demo video/GIF in the README; provide sample datasets |
| Guided ML workflow is too complex to scope cleanly | Delays MVP | Start with classification and regression on clean numeric data; expand later |

## 9. Success Metrics

Since this is a portfolio project, success is measured by:

- **Functional completeness:** All 8 MVP capabilities work end-to-end with at least 2 representative datasets (one numeric-heavy, one mixed-type).
- **Demo quality:** A recruiter watching a 2-minute demo video can understand what the tool does and why it's impressive.
- **Code quality:** The repository demonstrates clean architecture, good documentation, and AI-assisted development practices.
- **Export quality:** Exported notebooks run without errors when opened in a fresh Jupyter environment.

## 10. MVP Acceptance Criteria

| # | Capability | Testable Criteria |
|---|-----------|-------------------|
| 1 | Upload | User uploads CSV or Excel. Multi-sheet Excel shows a sheet picker. Invalid files show a clear error. |
| 2 | Initial summary | On upload, system displays row/column count, column names/types, quality issues, and 3–5 dataset-specific suggested questions within 15 seconds. |
| 3 | Conversational Q&A | User asks a free-text question; system returns results with charts and explanation. Code is hidden by default, visible via toggle. |
| 4 | Data cleaning | System surfaces cleaning suggestions after upload, during analysis when relevant, and after cleaning actions. Each suggestion includes actionable options. No changes applied without user confirmation. |
| 5 | Guided ML | User can complete a full predict workflow: target → features → preprocessing → train → evaluate. Each step includes a plain-English explanation. |
| 6 | Error recovery | When code execution fails, the user sees a plain-English error explanation and the system retries automatically. |
| 7 | Export | User downloads a `.ipynb` file that opens and runs in Jupyter without modification. |
| 8 | BYOK setup | User can enter an API key and the system validates it before proceeding. |
| 9 | Help | A help button is accessible from any screen. It explains the tool's capabilities, how to get started, example questions to ask, and how to obtain an API key. |
