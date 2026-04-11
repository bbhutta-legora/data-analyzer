# Implementation Plan Principles

Guidance for writing and maintaining `implementation_plan.md`. For principles about writing the actual code, see `coding_principles.md`.

---

## Examples in Planning Documents

You do not need to take any code written in a phase planning document literally, especially to the extent that the code there conflicts with `coding_principles.md`.

**However, examples in planning documents should model correct patterns:**
- Show tests before implementation code to reinforce "Testing First"
- Include expected output in verification sections
- Add `# REVIEW:` anchors for complex logic examples
- Document failure modes in example docstrings

This ensures the planning document itself teaches the right workflow, not just describes it.

---

## Scaffolding Steps

When a step involves project setup or scaffolding:

1. **Include explicit environment setup** — Don't assume dependencies are installed. Include:
   - Virtual environment creation (`python3 -m venv venv`)
   - Activation command (`source venv/bin/activate` or Windows equivalent)
   - Dependency installation (`pip install -r requirements.txt`)
   - Any required shell configuration or environment variables

2. **Verification must be runnable** — Every verification section should work immediately after completing the step, with no hidden prerequisites.

---

## Step Structure

Each step should include:

| Section | Purpose |
|---------|---------|
| **Goal** | One sentence describing the outcome |
| **Files to create/modify** | Explicit list of paths |
| **Step order** | For code changes: tests first, then implementation |
| **Tests FIRST** | Test code with docstrings linking to requirements |
| **Then Implementation** | Implementation code with verbose comments |
| **Verification** | Concrete commands with expected output |
| **Code Review** | Analyze all changed files against `harness/code_review_patterns.md` — fix violations before committing |

---

## Testing First

Per `coding_principles.md`, every step that produces code should:

1. Write tests first (show test code in the plan)
2. Run tests to verify they fail
3. Write implementation
4. Run tests to verify they pass
5. Run code review against `harness/code_review_patterns.md` on all changed files
6. Fix any violations found, then re-run tests to confirm they still pass
7. Commit only after the review passes

The plan itself should model this by showing test code **before** implementation code. No code is committed without passing the code review gate.

---

## Verification Sections

Verification commands should be:

- **Copy-pasteable** — No placeholders that require user substitution
- **Self-contained** — Include any setup commands (cd, activate venv, etc.)
- **Include expected output** — So the user knows what success looks like

### ✓ Good Verification

```markdown
**Verification**:
```bash
cd /path/to/project
source venv/bin/activate
pytest tests/test_module.py -v
```
**Expected output**: All tests passing, each showing PASSED status.
```

### ❌ Bad Verification

```markdown
**Verification**: Run the tests and check they pass.
```

---

## Dependencies Between Steps

- Each step should be independently completable given prior steps are done
- If Step N depends on Step M, state this explicitly
- Avoid circular dependencies

---

## Complexity Classification

Classify each step in the Summary table by complexity level:

| Level | Criteria |
|-------|----------|
| **Low** | Config changes, simple integrations, straightforward modifications with minimal logic |
| **Medium** | New functions with tests, refactoring with multiple touchpoints, async conversions |
| **High** | Architectural changes, complex algorithms, cross-cutting concerns, significant new abstractions |

Include a **Complexity** column in the Summary table. This helps with:
- Estimating effort and planning work sessions
- Identifying steps that may need extra review
- Deciding which steps to tackle when time is limited

---

## Deferred Features

When deferring features to later phases:

1. Document what's deferred and to which phase
2. Add placeholder code/comments where the feature will integrate
3. Ensure current implementation won't break when deferred feature is added
