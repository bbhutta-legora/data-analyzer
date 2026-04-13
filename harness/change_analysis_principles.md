# Change Analysis Principles

Before modifying existing code, produce a **change spec** — a lightweight artifact that captures what you're changing, why, and what must stay the same. This replaces the PRD for brownfield work.

---

## When to Use

Produce a change spec for any brownfield task:
- Bug fixes
- Feature additions to existing code
- Refactors
- Performance improvements
- Dependency upgrades that affect behavior

Skip for trivial changes where scope is self-evident (typo fix, config value update, adding a log line).

---

## Artifact Lifecycle

The change spec is a **branch-scoped artifact**. Create it as a file in the branch (e.g., `planning/change-spec-<short-description>.md`). It serves as context for the session and as a record of intent during the branch's lifetime.

**Clean it out when merging to main.** The change spec is working documentation, not permanent project history. The commit messages and PR description carry the "why" into main; the change spec's job is done. See also `harness/execution_plan_principles.md` § "Artifact lifecycle" for the shared lifecycle of all brownfield artifacts.

---

## Change Spec Format

### 1. What's changing and why

One paragraph. State the trigger (bug report, feature request, tech debt observation) and the goal.

### 2. Current behavior

Describe what the code does *now* in the affected area. Be specific — include function names, module paths, and observable behavior. This must be verified by reading actual code, not assumed from memory or documentation.

### 3. Desired behavior

Describe what the code should do *after* the change. Use the same level of specificity as the current behavior section so the delta is obvious.

### 4. Acceptance criteria

Concrete, testable conditions that define "done." Each criterion should be verifiable by running a test or observing a behavior. Format: "When [action], [expected outcome]."

### 5. Invariants to preserve

**The most important section for brownfield work.** List behaviors, contracts, and interfaces that must NOT change. These are the things you'll write characterization tests for and regression-check throughout execution.

Common invariants:
- API contracts (endpoint signatures, response shapes) that external callers depend on
- Data model fields/types that other modules read
- User-facing behaviors unrelated to the change
- Performance characteristics (if relevant)

If you can't articulate what should stay the same, you haven't understood the codebase well enough yet. Go back to reconnaissance.

### 6. Out of scope

Explicitly list adjacent improvements or cleanups you're choosing NOT to do in this change. This prevents scope creep and helps future sessions understand what was deliberately deferred.

---

## Eliciting the Change Spec

Use `harness/question_ordering.md` to ask the user clarifying questions. Prioritize questions that affect scope and invariants — these are the highest-leverage questions for brownfield work because they determine the blast radius.

Present the completed change spec to the user for confirmation before proceeding to codebase reconnaissance.
