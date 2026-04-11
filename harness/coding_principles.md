# Coding Principles

This codebase is developed entirely through AI-assisted coding. These principles ensure code remains understandable, verifiable, and maintainable across AI sessions.

## Phase planning documents

You do not need to take any code written in a phase planning document literally, esepcially to the extent that the code there conflicts with the principles here. 

---

## Testing First

Before writing code, first write a test for it. Write unit, integration, and functional tests as appropriate for the change.

**Follow the full TEST-STRATEGY.md process.** The test strategy prescribes human review gates (Steps 1–2) before any test code is written (Step 4). These gates cannot be skipped, even when an implementation plan or other planning document already contains test code. A planning document proposes tests at design time; the review steps confirm the user's intent at execution time. The user may have changed their mind, spotted new edge cases, or want to remove tests since the plan was written.

Concretely: present behaviors in plain English (Step 1) and specific test cases with expected failures (Step 2) to the user, and wait for confirmation before writing test files.

---

## Verification Guidance

After implementing any code change, **explicitly tell the user how to verify it works**. This should include:

1. **Specific commands to run** (e.g., test commands, curl requests, or scripts)
2. **Expected output or behavior** to confirm success
3. **Edge cases or failure modes** to manually check if relevant

Example:
> "To test this change, run `pytest tests/test_agent.py::test_new_feature -v`. You should see 1 test passing. You can also verify manually by running `python -m src.main` and checking that the output includes..."

Never assume the user knows how to test a change—always provide concrete verification steps.

---

## Verbose Commenting and Cross-References

Have verbose commenting on all code that explicitly links to:
- Related pieces of code (e.g., shared tests, dependent modules)
- The relevant section of `ARCHITECTURE.md` or `PRD.md`

Every file should have a header comment explaining:
- What this module does (one sentence)
- What feature(s) it supports (link to PRD section if applicable)
- Key dependencies and why they're needed

---

## Explicitness Over Inference

Prefer explicit types over inferred types. AI assistants modify code more reliably when types are visible at the point of use.

Avoid magic strings and numbers. Define constants with descriptive names that explain their purpose in the domain (e.g., `MAX_DOCUMENTS_PER_MATTER` rather than `100`).

---

## Naming for Greppability

Use unique, descriptive names that can be easily searched across the codebase. Avoid generic names like `handleClick`, `processData`, or `utils`.

Prefer full words over abbreviations (e.g., `documentCategory` over `docCat`).

---

## Small, Focused Changes

Each logical change should be independently testable. Avoid combining unrelated changes—this makes AI-generated code harder to verify and roll back.

---

## Error Handling Contracts

Every function that can fail should document its failure modes in a comment. When calling external services (Claude API, file system), use a consistent error-handling pattern so failures are traceable.

---

## Error Detection in Return Values

When checking if a function returned an error vs. valid content, avoid broad substring matching that could match content within successful responses.

### ❌ Anti-Pattern: Broad substring match
```python
# BAD: "not found" could appear in valid content (e.g., guidance text)
if "not found" not in result.lower():
    print("Success")
else:
    print("Failed")  # False positive if content contains "not found"!
```

### ✓ Pattern: Check specific error prefix
```python
# GOOD: Check for the exact error message format
if not result.startswith("Framework not found"):
    print("Success")
else:
    print("Failed")
```

### ✓ Better Pattern: Use structured returns
```python
# BEST: Return a tuple or dataclass with explicit success flag
def get_framework(name: str) -> tuple[bool, str]:
    if name in FRAMEWORKS:
        return (True, FRAMEWORKS[name])
    return (False, f"Framework not found: {name}")

success, result = get_framework("prospectus_summary")
if success:
    print("Success")
```

**Why this matters:** Framework content, documentation, and guidance text often contain words like "error", "not found", "failed", etc. as part of explaining how to handle those situations. Substring matching will produce false positives.

---

## State Transitions

For entities with status fields (e.g., session state, cleaning suggestion status), document the valid state transitions and what triggers them. This prevents invalid state changes.

---

## AI Logic Isolation

Keep all LLM prompts in `backend/llm.py` or as constants at the top of the file where they're used. Never inline prompts deep in business logic.

Document the expected input/output format for each AI call with example payloads in comments.

When parsing AI responses, always validate the structure before using. Treat AI outputs as untrusted external input.

---

## Review Anchors

When generating complex logic, include "review anchor" comments that flag areas requiring human verification:
- `// REVIEW: Complex conditional - verify this matches PRD section X`
- `// REVIEW: AI-generated regex - test with edge cases`

---

## Session State Access Patterns

All session state access goes through `backend/session.py`. No direct dictionary manipulation of the session store in route handlers.

Include the purpose of each state access as a comment (e.g., `# Retrieve the working dataframe for the current session`).

---

## Composition Over Conditionals

When adding new behavior, prefer adding a new well-named function that can be composed, rather than adding conditionals to existing functions. This keeps functions understandable in isolation.

## Zero-Ego Code

There is no ego in any of the codebase. If something does not make sense or can be rewritten to be more maintainable, take it out, especially where there is already test coverage for that code.

## Avoid High Cognitive Load

When reading code, you put things like values of variables, control flow logic and call sequences into your head. We should write code that decreases the number of such things that must be picked up on and remembered in order to write additional code. 

In these examples, we will refer to the level cognitive load as follows:

🧠: fresh working memory, zero cognitive load
🧠++: two facts in our working memory, cognitive load increased
🤯: working memory overflow, more than 4 facts
>

### Complex Conditionals

if (val > someConstant // 🧠+
    && (condition2 || condition3) // 🧠+++, prev cond should be true, one of c2 or c3 has be true
    && (condition4 && !condition5)) { // 🤯, we are messed up here
    ...
}

Some intermediate explanatory variables immediately decrease cognitive load:

const isValid = var > someConstant;
const isAllowed = condition2 || condition3;
const isSecure = condition4 && !condition5;
// 🧠, we don't need to remember the conditions, there are descriptive variables
if (isValid && isAllowed && isSecure) {
    ...
}

### Nested Conditionals

if (isValid) { // 🧠+, okay nested code applies to valid input only
    if (isSecure) { // 🧠++, we do stuff for valid and secure input only
        ... // 🧠+++
    }
}

If we add early returns, we can focus on each case by itself and on the happy path free our minds from all sorts of preconditions:

if (!isValid)
	return;

if (!isSecure)
	return;

// 🧠, we don't really care about earlier returns, if we are here then all good

... // 🧠+

---

## Python Module Principles

When working in `src/` modules:
- Avoid side effects at import time; keep I/O and API calls inside functions or `main()`
- Use a `if __name__ == "__main__":` guard for script execution
- Keep configuration in explicit constants or environment variables, not implicit globals

---

## Testing Parallel/Multiprocessing Code

When testing code that uses `ProcessPoolExecutor`, `ThreadPoolExecutor`, or similar concurrency primitives:

### Mock the Executor, Not the Submitted Function

When `ProcessPoolExecutor` submits a worker function, mocking the higher-level wrapper doesn't work—the executor calls the actual worker function. Mock the executor itself with a synchronous implementation:

```python
# ❌ BAD: Mocking draft_section doesn't work because the executor calls _draft_section_worker
with patch("src.orchestrator.draft_section", side_effect=mock_fn):
    results = draft_parallel_sections(...)  # Still calls real _draft_section_worker

# ✓ GOOD: Mock the executor with a synchronous implementation
class MockExecutor:
    def submit(self, fn, *args, **kwargs):
        result = mock_worker(*args, **kwargs)
        return MockFuture(result)
    def __enter__(self): return self
    def __exit__(self, *args): pass

with patch("src.orchestrator.ProcessPoolExecutor", MockExecutor):
    results = draft_parallel_sections(...)  # Uses mock executor
```

### Path Objects Don't Pickle

Worker functions submitted to process pools are pickled. `Path` objects can cause issues across process boundaries. Accept primitive types (strings) and convert inside the worker:

```python
# ❌ BAD: Path objects in worker signature
def worker(output_dir: Path) -> Dict:
    ...

# ✓ GOOD: Accept string, convert inside worker
def worker(output_dir_str: str) -> Dict:
    output_dir = Path(output_dir_str)
    ...
```

### Sandbox/Environment Limitations

Process pool tests may fail in sandboxed or restricted environments (e.g., pytest sandboxes, CI containers) due to semaphore/permission issues. Create mock executors that run synchronously for unit tests; reserve actual parallel execution for integration tests.

---

## Exported Notebook Quality

This project exports Jupyter notebooks (`exporter.py`). Ensure exported notebooks are self-contained:

- All necessary imports appear in the first code cell
- The dataframe loading cell uses a placeholder path that the user can replace
- Code cells and markdown explanation cells alternate in the order they were generated
- The exported notebook runs top-to-bottom in a fresh kernel without errors