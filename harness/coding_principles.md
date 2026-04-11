# Coding Principles

This codebase is developed entirely through AI-assisted coding. These principles ensure code remains understandable, verifiable, and maintainable across AI sessions.

## Phase planning documents

You do not need to take any code written in a phase planning document literally, esepcially to the extent that the code there conflicts with the principles here. 

---

## Testing First

Before writing code, first write a test for it. Write unit, integration, and functional tests as appropriate for the change.

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

For entities with status fields (Matter, Issue), document the valid state transitions and what triggers them. This prevents invalid state changes.

---

## AI Logic Isolation

Keep all Claude API prompts in dedicated files within `/lib/services/` or as constants at the top of the file where they're used. Never inline prompts deep in business logic.

Document the expected input/output format for each AI call with example payloads in comments.

When parsing AI responses, always validate the structure before using. Treat AI outputs as untrusted external input.

---

## Review Anchors

When generating complex logic, include "review anchor" comments that flag areas requiring human verification:
- `// REVIEW: Complex conditional - verify this matches PRD section X`
- `// REVIEW: AI-generated regex - test with edge cases`

---

## Database Query Patterns

All database queries go through `/lib/db/`. No raw Prisma calls in route handlers or components.

Include the purpose of each query as a comment (e.g., `// Fetch all unresolved issues for cascade calculation`).

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

## Legacy Notebook Notes (if editing ipynb)

When working with Jupyter notebooks, additional care is needed around cell execution order and variable scope.

### Avoid Redefining Constants Across Cells

When a constant is used by functions or data structures defined in earlier cells, do **not** redefine it in later cells. The earlier cell's dictionary/function may still reference the old value.

**Bad pattern:**
```python
# Cell 10 (Milestone 2)
FRAMEWORK = "short version"
FRAMEWORKS = {"key": FRAMEWORK}  # Dict holds reference to old string
def get_framework(): return FRAMEWORKS["key"]

# Cell 20 (Milestone 3)  
FRAMEWORK = "long version"  # ❌ FRAMEWORKS still points to old string!
```

**Good pattern — define constants BEFORE functions that use them:**
```python
# Cell 10 (Milestone 3) - Define constants first
FRAMEWORK = "long version"

# Cell 15 (Milestone 2) - Then define data structures and functions
FRAMEWORKS = {"key": FRAMEWORK}
def get_framework(): return FRAMEWORKS["key"]
```

**Alternative — rebuild the dict after redefining constants:**
```python
# Cell 20 (Milestone 3)
FRAMEWORK = "long version"
FRAMEWORKS = {"key": FRAMEWORK}  # Rebuild dict with new reference
```

### Document Cell Dependencies

When a cell depends on variables from specific earlier cells, add a comment:
```python
"""
Dependencies: 
- Cell 22: get_framework() function
- Cells 28-32: Framework constants (RISK_FACTORS_FRAMEWORK, etc.)
"""
```

### Test in Fresh Kernel State

After structural refactoring of notebook cells:
1. Restart the kernel (clearing all state)
2. Run all cells sequentially from top to bottom
3. Verify outputs match expectations

This catches hidden state dependencies where a variable was set in a previous run but wouldn't exist in a fresh execution.

### Prefer Single-Source-of-Truth for Constants

Rather than defining a constant in one milestone and "enhancing" it in another, define each constant in exactly one place. If the constant needs to be updated, update the original cell.

This avoids:
- Confusion about which definition is authoritative
- Stale references in dicts/closures
- Execution-order bugs