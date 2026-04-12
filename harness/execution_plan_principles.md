# Execution Plan Principles

Before writing any code for an implementation step, produce an **execution plan** and present it to the user for review. Do not begin Phase A (test spec) or any coding until the user confirms the plan.

The **implementation plan** (`planning/implementiton plan.md`) defines *what* to build and in what order. The **execution plan** defines *how* you will execute a specific step from that plan, right now, in this session.

Execution plans live within the session — they are not persisted to files.

---

## When to Produce an Execution Plan

Produce one whenever you are about to implement a step (or phase/sub-step) from the implementation plan. This includes:

- Starting a new step from the implementation plan
- Resuming a partially-completed step
- Implementing a bug fix or refactor that touches multiple files

Skip the execution plan for trivial changes (single-line fix, renaming, adding a comment) where the scope is self-evident.

---

## What the Execution Plan Contains

### 1. What we're building

One paragraph summarizing the goal, pulled from the implementation plan. Include the step number for traceability.

### 2. Current state

What already exists in the codebase that this step depends on or modifies. Verify by reading actual files — don't assume prior steps were completed exactly as the implementation plan describes.

### 3. Execution sequence

The phases of work, presented as a numbered list. Every execution plan uses this standard sequence:

| Phase | Name | What happens |
|-------|------|-------------|
| A | Test spec | Present behaviors and test cases to the user for review (TEST-STRATEGY.md Steps 1–2). Wait for confirmation. |
| B | Tests | Write test file(s), run them, confirm all fail for the right reasons (TEST-STRATEGY.md Steps 3–4). |
| C | Implementation | Write the production code to make tests pass (TEST-STRATEGY.md Step 5). |
| D | Verification | Break-the-implementation check, self-audit summary (TEST-STRATEGY.md Steps 6–7). Present for user confirmation. |
| E | Code review | Scan all changed files against `harness/code_review_patterns.md`. Fix violations, re-run tests. |
| F | Reflection | Follow `harness/reflection.md` — capture learnings, propose harness updates if warranted. |

Phases A–D follow TEST-STRATEGY.md. Phases E–F follow the mandatory code review and reflection gates from `document-routing.mdc`.

### 4. Implementation approach

Key design decisions for this step:

- What new files or modules will be created
- What existing files will be modified
- How functions will be decomposed (especially I/O vs. pure logic separation)
- What shared constants or types need to be introduced
- Whether async, multiprocessing, or other infrastructure patterns apply

### 5. Deviations from the implementation plan

Where the implementation will differ from what the planning document proposes, and why. Common reasons:

- The planning document's code conflicts with `coding_principles.md` or `framework_patterns.md`
- The current codebase has evolved since the plan was written
- A simpler or more robust approach exists

If there are no deviations, say so explicitly.

---

## What the Execution Plan Does NOT Contain

- **Behaviors to test** — those are proposed during Phase A, not upfront. The user may have changed their mind since the plan was written.
- **Test code or implementation code** — the plan is a roadmap, not a code dump.
- **Detailed prompt templates or API schemas** — those emerge during implementation.

---

## Presenting the Plan

End the execution plan with a clear prompt asking the user to confirm, adjust, or reject before you proceed. Example:

> "Does this plan look good? Would you like to adjust the scope, implementation approach, or phasing before I begin?"

Only after the user confirms should you move into Phase A.
