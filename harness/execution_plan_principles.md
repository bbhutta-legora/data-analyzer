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
| D | Verification | Break-the-implementation check (state what you're breaking, which tests should fail, and why before touching code), self-audit summary (TEST-STRATEGY.md Steps 6–7). Present for user confirmation. |
| E | Code review | Scan all changed files against `harness/code_review_patterns.md`. Fix violations, re-run tests. |
| F | Reflection | Follow `harness/reflection.md` — capture learnings, propose harness updates if warranted. |

Phases A–D follow TEST-STRATEGY.md. Phases E–F follow the mandatory code review and reflection gates from `document-routing.mdc`.

#### Wireframe phase for UI changes

Whenever a step creates or significantly changes frontend UI, insert a **Phase A0 — Wireframes** before the test spec — regardless of whether the step also includes backend work:

| Phase | Name | What happens |
|-------|------|-------------|
| A0 | Wireframes | Present 2–3 markdown wireframe options showing layout, element placement, and content hierarchy. Wait for the user to pick a direction (or request changes) before proceeding. |

Why this matters: frontend components are primarily *visual* artifacts. Reviewing a wireframe catches layout and UX issues far earlier than reviewing test cases or code. The wireframe doesn't need to be pixel-perfect — it shows spatial relationships, element grouping, and interaction flow using ASCII/markdown box diagrams.

The wireframe phase applies whenever the step:
- Creates new UI components (modals, panels, screens, cards)
- Significantly restructures existing layout
- Introduces a new interaction pattern (wizard, drag-and-drop, etc.)

This includes mixed backend+frontend steps (e.g., Step 7 creates both `llm.py` and `FileUpload.tsx` / `DataSummary.tsx`). The backend can proceed through the standard phases (A–F) without wireframes, but the frontend components must go through A0 before implementation.

Skip A0 when the frontend change is purely behavioral with no visible layout change (e.g., wiring a click handler to an existing button, changing a store action).

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

### 6. Decisions needing user input

List any ambiguities, trade-offs, or design choices that cannot be resolved from the implementation plan or codebase alone. These are questions where reasonable engineers could disagree, and the user's preference matters.

For each decision, provide:
- A clear statement of the choice
- The options (with a brief pro/con for each)
- A recommendation if you have one

Common triggers for decisions:
- The implementation plan assumes a data model that has since changed
- Multiple valid UX approaches exist (e.g., one-click vs. confirm dialog)
- A feature could be simple-now or extensible-later
- The plan is silent on an important detail

Surfacing decisions upfront — rather than making assumptions during implementation — avoids rework and ensures the user stays in control of product direction.

---

## Refactor-Specific Guidance

Refactors follow the same phases (A–F) but differ from feature steps in a few important ways.

### Phase A is about diffs, not behaviors

For a refactor, the behaviors being tested mostly already exist — they passed before and should still pass after. Phase A should focus on:

1. **What changes in the test contracts** — new field names, renamed variables, updated assertions
2. **Any genuinely new behaviors** introduced by the redesign (e.g. multi-DataFrame isolation)
3. **Explicitly skipping behaviors** that are purely mechanical fixture updates with no semantic change

Do not re-present the full behavior list from scratch. Present the delta.

### Verify existing tests fail for the right reason

When updating tests for a refactor, a test that fails with `AttributeError: object has no attribute 'new_name'` is failing for the right reason — the implementation hasn't been updated yet. A test that fails with a logic assertion error may mean the test was updated incorrectly. Check carefully before proceeding to Phase C.

### Break check targets the new invariant, not the old one

For refactors, the break-the-implementation check should deliberately break the *new* behavior introduced by the refactor (e.g. the independent copy invariant), not a behavior that existed before. The pre-existing behaviors are already covered by prior tests.

### Planning docs almost always need updating

Refactors change module interfaces, data models, or API contracts — all of which are documented in `planning/architecture.md`. Phase F should always update architecture to reflect the new structure, and check `planning/implementiton plan.md` for any remaining steps that reference the old structure.

---

## What the Execution Plan Does NOT Contain

- **Behaviors to test** — those are proposed during Phase A, not upfront. The user may have changed their mind since the plan was written.
- **Test code or implementation code** — the plan is a roadmap, not a code dump.
- **Detailed prompt templates or API schemas** — those emerge during implementation.
- **Resolved decisions** — once the user answers the questions in Section 6, incorporate their answers into the plan and proceed. Don't carry answered questions forward.

---

## Presenting the Plan

End the execution plan with a clear prompt asking the user to confirm, adjust, or reject before you proceed. Example:

> "Does this plan look good? Would you like to adjust the scope, implementation approach, or phasing before I begin?"

Only after the user confirms should you move into Phase A.
