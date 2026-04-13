# Codebase Reconnaissance

Before executing a brownfield change, conduct a systematic investigation of the code you're about to modify. The goal is to build a mental model of the affected area — its dependencies, behaviors, test coverage, and coupling — so you can scope the blast radius and sequence the work safely.

---

## When to Conduct Reconnaissance

Conduct full reconnaissance for any brownfield change that:
- Modifies a function called by more than one caller
- Touches a module boundary (imports, exports, API contracts)
- Changes a data structure used across modules
- Involves code you haven't read in this session

Skip or abbreviate for changes that are clearly contained: a bug fix inside a single function with no callers affected, a config change, a string update.

---

## Reconnaissance Checklist

Work through these in order. Each step builds on the previous one.

### 1. Dependency Mapping

Trace the code in both directions from the change point.

**Upstream (who calls this):**
- Direct callers of the function/class being changed
- Route handlers or entry points that eventually reach this code
- Tests that exercise this code path

**Downstream (what this calls):**
- Functions, modules, and external services this code depends on
- Shared state it reads or writes (session state, global variables, database)
- Side effects (file I/O, network calls, logging)

For each dependency, note whether the change affects the interface (signature, return type, error behavior) or only the internals.

### 2. Data Flow Tracing

Follow the data through the change area:
- What are the input shapes? (types, fields, constraints)
- What transformations happen?
- What are the output shapes?
- Are there implicit contracts? (e.g., "this field is always present when status is 'active'")

Pay special attention to data structures that cross module boundaries — these are the highest-risk points for breakage.

### 3. Existing Test Inventory

Catalog what's already tested in the affected area:
- Which functions/behaviors have test coverage?
- What test files cover this area? List them.
- Are the existing tests unit tests, integration tests, or end-to-end?
- Are there any tests that are flaky, skipped, or known-broken?

**What's NOT tested is as important as what is.** Untested code that your change touches is where regressions hide.

### 4. Implicit Contracts

Identify behaviors that aren't documented or tested but that callers rely on:
- Does caller code assume a specific error format? (e.g., checking for a string prefix)
- Does caller code assume ordering of results?
- Are there timing assumptions? (e.g., "this completes before that starts")
- Are there assumptions about state? (e.g., "session always has a dataframe by the time this runs")

These are the behaviors most likely to break silently because no test catches them.

### 5. Coupling Assessment

Classify how entangled the change area is:

| Level | Indicators | Implication |
|---|---|---|
| **Low coupling** | Pure function, no shared state, few callers | Change is safe to make in isolation |
| **Medium coupling** | Reads shared state, multiple callers, but stable interface | Need characterization tests for callers |
| **High coupling** | Writes shared state, callers depend on implementation details, no clear interface | May need preparatory refactor before the change |

---

## Blast Radius Classification

Based on the reconnaissance, classify the overall blast radius:

| Blast radius | Description | What it means for execution |
|---|---|---|
| **Contained** | Change is internal to one function/module, no callers affected | Standard execution. Characterization tests optional but recommended. |
| **Interface** | Change affects a module's API — callers need updating | Characterization tests mandatory. Update callers as part of the change. Run full test suite at every step. |
| **Cross-cutting** | Change affects shared infrastructure, data models, or contracts | Characterization tests mandatory. Consider a preparatory refactor to isolate the change. May need to break the work into multiple smaller changes. Full test suite at every step. |

For each affected area, assess:
- **Test coverage:** Does a safety net exist? (yes / partial / no)
- **Caller count:** How many places need updating if the interface changes?
- **Backward compatibility:** Is the change additive or breaking?
- **Risk severity:** What's the worst outcome if this area breaks? (data loss, silent corruption, user-visible error, cosmetic issue)

---

## Reconnaissance Output

Produce a **reconnaissance document** as a branch-scoped artifact (e.g., `planning/recon-<short-description>.md`). This document is committed to the branch during development and removed upon merge to main — same lifecycle as the change spec (see `harness/execution_plan_principles.md` § "Artifact lifecycle" and `harness/change_analysis_principles.md` § "Artifact Lifecycle").

The reconnaissance document should contain:

1. **Affected files and functions** — list with one-line descriptions
2. **Dependency map** — who calls what, in both directions
3. **Test coverage status** — what's covered, what's not
4. **Blast radius classification** — contained / interface / cross-cutting
5. **Key risks** — the 2–3 things most likely to go wrong

Present the findings to the user for confirmation. This feeds directly into sequencing decisions in the brownfield execution phases.
