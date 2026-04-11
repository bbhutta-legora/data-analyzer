# Smart Dataset Explainer — Test Strategy

How we write and run tests in this project. This document is prescriptive — follow this process for every new test.

---

## Principles

1. **Tests protect behaviors you'd be upset about if they broke.** Don't test CSS classes, loading skeletons, or third-party library internals. Test the things that matter: parsing, state transitions, data writes, AI response handling.

2. **Tests are written before implementation.** When building new features or refactoring, tests come first. They define "done." The implementation's job is to make them pass.

3. **The human writes the spec, the AI writes the code.** You describe what should happen in plain English. The AI translates that into test code. You review and confirm before implementation begins.

4. **Tests and implementation are never written in the same step.** The test represents your intent. The implementation meets it. Writing both together lets them agree with each other instead of agreeing with you.

---

## Process

Every test cycle follows these steps. Do not skip steps.

### Step 1: Identify what to test (AI + you)

You point the AI at a piece of the system — a function, a feature, a refactor decision — and tell it what area you care about. You can be as vague as "I want to test the task parser" or as specific as "I want to make sure marking a task done writes to the markdown file correctly."

The AI then:

1. **Reads the relevant code** (or the refactor decision if it's new behavior).
2. **Proposes a list of behaviors worth testing** — described in plain English, not code. Each behavior is one sentence: what the thing does and why it matters.
3. **Flags which behaviors are high-risk** — the ones most likely to break or cause user-visible problems.
4. **Calls out non-obvious edge cases** — things you might not think of but would bite you (e.g. "What happens if TASKS.md has no `## Active` section at all?" or "What if a task title contains markdown characters like `**` or `|`?").

You review the list. Cross off anything you don't care about. Ask questions about anything you don't understand. Add anything the AI missed that you know matters from using the product.

The output of this step is a confirmed list of behaviors to test, in plain English.

### Step 2: Define specific test cases and expected failures (AI, reviewed by you)

For each behavior from Step 1, the AI proposes specific test cases with concrete inputs and outputs:

Before writing any test code, the AI turns each confirmed behavior into specific test cases:

Format:

```
Test 1: [name]
  Input: [what goes in]
  Expected: [what should come out]
  Expected failure: "Expected [X] but received [Y]" or "Function not found" etc.

Test 2: [name]
  ...
```

**You review this list.** Remove tests you don't care about. Add cases the AI missed. Confirm the expected failures make sense — they should describe the *behavior* being wrong, not a setup error.

Only proceed to Step 3 after you've confirmed.

### Step 3: Write the test descriptions (you, optional)

If any of the AI's proposed test cases don't match your intent, refine them here. You can write or adjust descriptions using this template:

> "When [input / action], it should [observable result]. If [edge case], it should [fallback behavior]."

Keep descriptions focused on one behavior each. If you find yourself writing "and also," that's two tests.

This step is optional — if the AI's proposals from Step 2 look right, just confirm and move on.

### Step 4: Write and run the tests (AI)

The AI writes the test file and runs it. Every test should fail at this point (since the implementation doesn't exist yet or the behavior hasn't changed yet).

The AI provides:

1. The test file location and contents.
2. The command to run the tests (e.g. `pnpm test path/to/test`).
3. **For each failing test:** the actual failure message, with a note on whether it's failing for the right reason.

**How to verify a test fails for the right reason:**

| Failure type | What it looks like | Is it right? |
|---|---|---|
| Behavior assertion failed | "Expected task in ## Done, received task in ## Active" | **Yes** — the test is checking the right behavior, it just doesn't exist yet. |
| Function/module not found | "Cannot find module '@/lib/tasks/markDone'" | **Maybe** — if the function doesn't exist yet and will be created during implementation, this is expected. If the import path is wrong, fix the test first. |
| Type error or syntax error | "Property 'x' does not exist on type 'Y'" | **No** — the test itself has a bug. Fix before proceeding. |
| Test passes | "✓ marks task as done" | **No** — either the behavior already exists (verify that) or the test is broken and would pass regardless. Investigate before proceeding. |

If any test is failing for the wrong reason, fix the test before moving to implementation.

### Step 5: Implement (AI)

The AI writes the implementation to make all failing tests pass. It runs the tests after implementation and confirms they all pass.

**Iteration cap:** If the AI tries more than 3 attempts to make a test pass without success, it must stop and escalate — not with code, but with a plain-English summary:

> "The test expects [X]. The code produces [Y]. Here's why I think [Y] might actually be correct: [reason]."

You judge based on the behavior description from Step 1, not the code. If the code's actual behavior matches your original intent better than the test expectation, the test is wrong (false negative — see Guarding Against Broken Tests below). If the test expectation matches your intent, the implementation is wrong and the AI continues.

**All failures surfaced in plain English.** When a test fails during implementation, the AI translates the failure into natural language. Not "Expected 'done', received 'active'" but "The test expected the task to be in the Done section, but the code put it in the Active section." You compare two English descriptions of behavior against your intent — you never need to read the test code or the implementation code.

### Step 6: Verify tests are real (AI)

After all tests pass, the AI does two checks:

**Break-the-implementation check.** The AI deliberately breaks the key behavior in the implementation (e.g. comments out the line that moves the task) and runs the tests again. If the tests still pass, they aren't checking the behavior — the test is a false positive and must be fixed before proceeding. After the check, the AI restores the implementation.

**Self-audit.** The AI writes a plain-English summary of what it built:

> "Here's what I built: when you mark a task done, it reads TASKS.md, finds the task line under ## Active, moves it to the ## Done section, and appends [DONE:2026-03-31] to the description."

You compare this to your original description from Step 1. If they match, you're good. If the summary describes something different or convoluted, the test may have forced the AI down the wrong path.

### Step 7: Final confirmation (you)

You confirm:
- Does the self-audit summary match what you asked for?
- Run the full test suite (`pnpm test`) — did anything else break?
- If both are good, the cycle is complete.

---

## Guarding Against Broken Tests

Tests can be broken in two ways. Both are defended against at multiple points in the process.

### False positives (test passes when it shouldn't)

The test is broken in a way that makes it always pass — even if the implementation is wrong. This gives silent false confidence.

| Defense | When | How |
|---|---|---|
| Step 2 review | Before tests are written | You review proposed test cases in plain English. If the expected output doesn't match your intent, catch it here. |
| Step 4 pre-implementation check | After tests are written, before implementation | If a test passes before any implementation exists, something is wrong. Investigate. |
| Step 6 break-the-implementation | After implementation | AI deliberately breaks the key behavior. If tests still pass, they're fake. |

### False negatives (test fails when it shouldn't)

The test is broken in a way that makes it always fail — even if the implementation is correct. The AI may contort the implementation to satisfy a broken test.

| Defense | When | How |
|---|---|---|
| Step 2 review | Before tests are written | You review proposed test cases in plain English. If the expected output doesn't match your intent, catch it here. |
| Step 5 iteration cap | During implementation | After 3 failed attempts, the AI stops and shows you what the test expects vs what the code produces — in plain English. You judge which matches your intent. |
| Step 5 plain-English failures | During implementation | Every failure is translated to natural language so you can spot when the test expectation sounds wrong. |
| Step 6 self-audit | After implementation | If the AI's summary of what it built sounds convoluted or different from what you asked for, the test may have forced it down the wrong path. |

---

## What to test (priority order)

### High priority — test these first

1. **LLM response parsing** (`llm.py`) — parsing structured JSON from non-deterministic LLM output is the most fragile boundary. Test code-fence stripping, missing fields, malformed JSON, and edge cases like trailing prose.
2. **Sandboxed code execution** (`executor.py`) — test that LLM-generated code runs correctly, figures are captured as base64, restricted imports are blocked, and timeouts fire.
3. **Session lifecycle** (`session.py`) — session creation, dataframe storage, conversation history management, and cleanup.
4. **Prompt construction** (`llm.py`) — given a dataframe's metadata and conversation history, does the prompt include the right context?

### Medium priority

5. **API route contracts** (`main.py`) — mock the LLM and executor, verify each endpoint returns the right shape for valid input and a meaningful error for invalid input (correct HTTP status codes, Pydantic-validated responses).
6. **Notebook export** (`exporter.py`) — verify the exported `.ipynb` is valid JSON, contains the expected cells, and is runnable.

### Low priority — defer these

7. **Frontend component rendering** — only test if a component has complex conditional logic. Don't test that a button renders.
8. **Zustand store behavior** — test only if store logic goes beyond simple set/get.

---

## Infrastructure

### Backend (Python)

- **Test runner:** pytest
- **Test location:** `backend/tests/`, mirroring the source module names. E.g. `backend/tests/test_session.py`.
- **Running tests:**
  - All tests: `pytest backend/tests/ -v`
  - Specific file: `pytest backend/tests/test_session.py -v`
- **Mocking:** `unittest.mock` (`patch`, `MagicMock`) for LLM API calls and file I/O.

### Frontend (TypeScript)

- **Test runner:** Vitest
- **Test location:** `frontend/tests/` or co-located `*.test.tsx` files.
- **Running tests:**
  - All tests: `npm test` (from `frontend/`)
  - Watch mode: `npm test -- --watch`
- **Mocking:** Vitest built-in `vi.mock()` for API client mocks.
