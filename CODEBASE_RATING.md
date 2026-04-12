# Codebase Rating: Smart Dataset Explainer

## Overview

This is an AI-powered conversational data analysis tool for junior data scientists. It features a React/TypeScript frontend and a Python/FastAPI backend. The backend handles LLM integration (OpenAI/Anthropic), sandboxed code execution, data cleaning, guided ML workflows, and Jupyter notebook export. **13 of 15 implementation steps are complete** — Step 13 (Guided ML frontend) is the notable gap.

---

## Dimension Ratings

### 1. Architecture & Design — 9/10

**Strengths:**
- Clean separation of concerns: 7 backend modules with well-defined boundaries (`main.py` for routing, `llm.py` for prompts, `executor.py` for sandboxing, `clean.py` for pure transforms, `session.py` for state, `providers.py` for config, `exporter.py` for export).
- Pure functions are separated from I/O functions throughout — `clean.py` is entirely pure, `llm.py` separates prompt builders from API callers, making unit testing trivial without mocks.
- Single source of truth pattern applied consistently: `sandbox_libraries.py` feeds both the exec namespace and LLM system prompt; `providers.py` feeds both backend validation and the frontend model dropdown.
- The decision to keep `exec()` in-process with multiprocessing isolation is well-justified and documented in the architecture doc.
- State machine for ML stage progression is clean with explicit validation.

**Gaps:**
- The architecture doc references a `README.md` that doesn't exist.
- Thread-safety is explicitly called out as a known limitation in `SessionStore` but not addressed.

### 2. Code Quality — 8.5/10

**Strengths:**
- Consistent module-level header comments referencing PRD capabilities and architecture sections.
- Functions have clear docstrings documenting failure modes, which is uncommon and very helpful.
- String concatenation used deliberately over f-strings in prompt building to avoid `KeyError` from column names with curly braces — well-reasoned defensive coding.
- Constants are named and documented (e.g., `MAX_UPLOAD_FILE_SIZE_BYTES`, `CLASSIFICATION_UNIQUE_VALUE_THRESHOLD`).
- No mutable default arguments. No bare `except` clauses (the one broad `except Exception` in upload parsing is documented).
- Clean use of `frozenset` for `VALID_ACTIONS`, frozen dataclass for `ModelInfo`.

**Gaps:**
- Frontend uses inline styles pervasively rather than CSS modules or a design system — functional but harder to maintain at scale.
- Some repeated patterns in SSE event generation could be slightly DRYer (though the repetition is minor).
- The `_build_retry_prompt` uses raw string concatenation that, while safe, is hard to read compared to a template approach.

### 3. Security — 7/10

**Strengths:**
- Sandbox removes `__import__`, `open`, `eval`, `exec`, `compile`, `globals`, `locals` from builtins.
- Process-level isolation with `multiprocessing.Process` + `kill()` on timeout prevents runaway code.
- API key is held in-memory per session only, never persisted.
- File upload validates extension, size, and non-emptiness before parsing.
- CORS is restricted to the dev frontend origin.
- Filename escaping in notebook export (`exporter.py:83-84`) prevents injection.

**Gaps:**
- The blocklist approach for builtins is acknowledged as weaker than an allowlist — new Python builtins in future versions would be allowed by default. The code has a `REVIEW` comment about this.
- `exec()` with restricted globals is not a true sandbox — determined attackers could escape it (e.g., via `type.__subclasses__()` chain). Acceptable for a portfolio project as stated in the PRD non-goals, but worth noting.
- No rate limiting on API endpoints.
- API key is transmitted as a form field on upload — fine over HTTPS but exposed in server logs without redaction.

### 4. Testing — 8/10

**Strengths:**
- **4,275 lines of test code** covering 12 backend test files and 4 frontend test files against **4,742 lines of source** — roughly 0.9:1 test-to-source ratio, which is excellent.
- Tests cover the core modules: upload, chat, cleaning, error recovery, ML workflow, executor, exporter, LLM prompt parsing, session management, history truncation, providers, and key validation.
- Frontend tests include component tests (ChatPanel, MessageBubble) and unit tests (API client, store).
- Test strategy documented in `harness/TEST-STRATEGY.md`.

**Gaps:**
- No integration test infrastructure for the full end-to-end flow (acknowledged as a separate optional suite).
- Frontend test coverage is thinner — only 2 component test files vs. 7 components.
- No test for `HelpModal`, `FileUpload`, `DataSummary`, `CleaningSuggestionCard`, or `ApiKeyInput` components.

### 5. Documentation — 8.5/10

**Strengths:**
- Thorough **PRD** (154 lines) with clear goals, non-goals, acceptance criteria, and risk matrix.
- Detailed **architecture document** (310 lines) covering module responsibilities, request flows, state shapes, communication protocol, sandboxing strategy, and decision log.
- **Implementation plan** with step-by-step tracking, mandatory code review checklist, and clear status markers (13/15 steps done).
- `harness/` directory contains process documents: test strategy, code review patterns, coding principles, architectural principles, reflection notes.
- Every source file has header comments referencing PRD capability numbers and architecture section links.

**Gaps:**
- No README.md — a significant omission for a portfolio project.
- No API documentation (OpenAPI/Swagger is auto-generated by FastAPI but not explicitly configured).
- The implementation plan filename has a typo: `implementiton plan.md`.

### 6. Completeness / Feature Coverage — 7.5/10

**Strengths:**
- 8 of 9 PRD capabilities have backend implementations complete: Upload, Initial Summary, Conversational Q&A, Data Cleaning, Guided ML (backend), Error Recovery, Export, BYOK, Help.
- The ML backend has all 6 stages implemented: target selection, feature selection, preprocessing, model selection, training, explanation.

**Gaps:**
- **Step 13 (Guided ML frontend)** is the only unimplemented step — the backend endpoint exists and is tested, but there's no UI for the multi-stage ML wizard. This is a meaningful gap since "Guided ML" is one of the 5 stated PRD goals.
- No sheet picker UI for multi-sheet Excel files (the backend parses all sheets, but the PRD calls for a user selection step).
- The chat SSE stream doesn't include `code` in the SSE events — the assistant messages in the store never get the `code` field populated, so the "Show code" toggle in `MessageBubble` would never render.

### 7. Frontend Quality — 6.5/10

**Strengths:**
- Clean component decomposition matching the architecture doc.
- Zustand store is well-typed with clear action methods.
- SSE client handles POST-based SSE correctly (using fetch + ReadableStream since EventSource only supports GET).
- Good error handling patterns: friendly user messages with "Show details" toggles.
- Accessibility basics present: `role="alert"`, `aria-label`, `aria-hidden`.
- Proper cleanup with `cancelled` flag in useEffect.

**Gaps:**
- All styling is inline — no CSS modules, no design system, no theming. This works but is fragile for a production app.
- No loading/skeleton states for the chat screen.
- No responsive design considerations beyond `min(400px, 85vw)` on the help panel.
- `key={idx}` used for message lists (should use stable IDs to avoid reconciliation issues).
- Missing `code` field propagation in the chat SSE flow means the code toggle feature doesn't actually work.
- No syntax highlighting for the code toggle (just `<pre>` with a dark background).

### 8. Error Handling — 8.5/10

**Strengths:**
- Comprehensive error recovery: the chat endpoint retries once with error context and timeout guidance.
- Error types are structured (`{"error": "<type>", "detail": "<message>"}`) consistently across all endpoints.
- LLM response parsing gracefully degrades: malformed JSON returns `{"error": ...}` instead of raising.
- Executor distinguishes user-code errors from infrastructure errors with different messaging.
- Frontend handles network errors, API errors, and stream errors with user-friendly messages.
- Conversation history records only successful outcomes — failed retries don't pollute LLM context.

**Gaps:**
- Only 1 retry attempt (`MAX_CHAT_RETRIES = 1`). For LLM-generated code, 2 retries might be more appropriate.
- No retry logic on the ML step endpoint (only the chat endpoint retries).

### 9. Developer Experience — 7.5/10

**Strengths:**
- Vite proxy configured for seamless frontend-to-backend development.
- Test setup files configured for both Vitest and pytest.
- `.gitignore` covers common artifacts (node_modules, venv, __pycache__, .env, dist).
- Module headers consistently link to architecture docs and PRD capabilities.

**Gaps:**
- No README with setup instructions — a new developer has to read the implementation plan to know how to start the project.
- No `Makefile`, `docker-compose.yml`, or scripts for one-command startup.
- No linting configuration (no `.eslintrc`, no `ruff.toml`, no `pyproject.toml`).
- No CI/CD configuration.
- No type checking configured for the backend (no `mypy` or `pyright`).

### 10. Maintainability — 8/10

**Strengths:**
- Flat module structure — 7 backend modules, no sub-packages, no abstract base classes. Easy to navigate.
- Cross-references between source files and planning docs make it easy to trace why code exists.
- Decision log in the architecture doc explains trade-offs.
- Harness documents capture coding principles and patterns for future contributors.

**Gaps:**
- Some long files: `main.py` is 1,076 lines; `llm.py` is 993 lines. While individual functions are reasonable, the file-level length is high.
- Frontend lacks a component library or shared style constants.

---

## Summary Table

| Dimension | Score | Notes |
|---|---|---|
| Architecture & Design | 9/10 | Clean separation, single-source-of-truth patterns, well-documented decisions |
| Code Quality | 8.5/10 | Defensive coding, clear naming, consistent patterns; inline styles are the main weakness |
| Security | 7/10 | Reasonable for a portfolio project; blocklist sandbox has known theoretical escapes |
| Testing | 8/10 | ~0.9:1 test-to-source ratio; backend well-covered, frontend thinner |
| Documentation | 8.5/10 | Excellent planning docs; missing README is a notable gap for a portfolio project |
| Completeness | 7.5/10 | 13/15 steps done; ML frontend and code-toggle SSE integration are the gaps |
| Frontend Quality | 6.5/10 | Functional but rough — all inline styles, no responsive design, code toggle non-functional |
| Error Handling | 8.5/10 | Structured errors, retry logic, graceful degradation throughout |
| Developer Experience | 7.5/10 | Good dev-server setup; no README, no linting, no CI |
| Maintainability | 8/10 | Flat, traceable structure; some files getting long |

**Overall: 7.9/10** — A well-architected backend with strong testing and documentation practices, held back by an incomplete frontend (missing ML wizard, non-functional code toggle), absence of a README, and rough frontend polish. The backend is notably above average for a portfolio project.
