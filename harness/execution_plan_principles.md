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
| A0 | Wireframes | Present 2–3 wireframe options showing layout, element placement, and content hierarchy. Wait for the user to pick a direction (or request changes) before proceeding. |

Why this matters: frontend components are primarily *visual* artifacts. Reviewing a wireframe catches layout and UX issues far earlier than reviewing test cases or code.

The wireframe phase applies whenever the step:
- Creates new UI components (modals, panels, screens, cards)
- Significantly restructures existing layout
- Introduces a new interaction pattern (wizard, drag-and-drop, etc.)

This includes mixed backend+frontend steps (e.g., Step 7 creates both `llm.py` and `FileUpload.tsx` / `DataSummary.tsx`). The backend can proceed through the standard phases (A–F) without wireframes, but the frontend components must go through A0 before implementation.

Skip A0 when the frontend change is purely behavioral with no visible layout change (e.g., wiring a click handler to an existing button, changing a store action).

#### Interactive HTML mockup for Phase A (UI steps)

When a step involves frontend UI, Phase A (test spec) must include an **interactive HTML mockup** alongside the text-based behavior list. The mockup replaces text-only wireframes as the primary review artifact for UI behaviors.

**What the mockup is:**

A single self-contained `.html` file (written to the workspace root as a temporary artifact, deleted after review) that the user opens in a browser. It is a clickthrough prototype — not a functional app — that demonstrates each testable behavior visually.

**Structure:**

- **Left panel:** A framed mockup of the app, rendered scene-by-scene. Each scene shows a specific state (e.g., "wizard target stage with nothing selected," "features stage after target confirmed"). Interactive elements relevant to the current behavior are highlighted with a visual glow.
- **Right sidebar:** The full list of behaviors from the test spec. Behaviors demonstrated in the current scene are highlighted; others are faded. Each behavior shows its ID, description, and risk level.
- **Navigation:** Prev/Next buttons and arrow-key support to step through scenes.

**Why this matters:**

- Behaviors like "Confirm is disabled until a selection is made" are immediately obvious in a visual mockup but easy to misunderstand in text.
- The clickthrough flow shows state transitions (collapsed cards, loading states, error boxes) that ASCII diagrams struggle to convey.
- Reviewing a mockup catches UX issues (element placement, flow, missing states) that text specs miss.

**When to use:**

Use the interactive HTML mockup whenever Phase A covers UI behaviors — i.e., whenever Phase A0 (wireframes) was triggered for the step.

**Lifecycle:**

The mockup file is temporary. Delete it from the workspace after the user confirms the test spec. It is not committed to version control.

#### Visual artifacts for Phase A (general preference)

There is a general preference for visual artifacts when presenting test specs for review. Seeing behaviors is faster and more reliable than reading about them. The format scales to the complexity:

| Step type | Visual artifact | Format |
|-----------|----------------|--------|
| **Frontend UI** | Required | Interactive HTML mockup (see above) |
| **Backend with branching/state/sequencing** | Recommended | Markdown diagrams in the chat (ASCII state machines, event timelines, error decision trees) |
| **Backend with simple input→output** | Skip | Text-based behavior list is sufficient |

**When to produce a markdown diagram for backend steps:**

Use a markdown diagram when the behaviors involve:
- **State machines** — stage progression, session lifecycle, workflow transitions. Draw the states and edges, annotate which behaviors are tested on which transitions.
- **Event sequences** — SSE streams, multi-step async flows. Show the timeline of events with payload shapes.
- **Error decision trees** — endpoints with multiple branching error conditions. Show the tree from request → condition checks → response outcomes.
- **Data transformation pipelines** — multi-stage parsing or processing. Show the data shape at each step.

Skip the diagram when behaviors are simple input→output mappings (e.g., "given this history, `build_notebook` returns valid JSON"). The "When [X], [Y]" text format is sufficient for those.

Unlike the HTML mockup for frontend steps, backend diagrams are **inline markdown in the chat** — no separate file needed. They supplement the text-based behavior list rather than replacing it.

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

## Brownfield Execution

Brownfield changes follow a different phase sequence than greenfield. The core difference: before you change anything, you must understand and protect what already works.

### When to use brownfield execution

Use this sequence when the change modifies existing code rather than creating new modules from scratch. The change spec (`harness/change_analysis_principles.md`) and codebase reconnaissance (`harness/codebase_reconnaissance.md`) must be complete before brownfield execution begins. Both produce branch-scoped artifacts (see Artifact Lifecycle below).

### Brownfield phase sequence

| Phase | Name | What happens |
|-------|------|-------------|
| B0 | Baseline | Run the full existing test suite. Record the result. If tests are already failing, document which ones and why — these are pre-existing, not your problem. This is your green baseline. |
| B1 | Test spec + write | Present ALL test specs to the user: characterization tests for untested invariants AND feature tests for new/changed behavior. User confirms. Write all tests. Characterization tests pass, feature tests fail for the right reasons. |
| B2 | Preparatory refactor | Only if reconnaissance revealed high coupling that makes the change risky. Refactor to isolate the change point. Characterization tests still pass, feature tests still fail. Skip if coupling is low or medium. |
| C | Implementation | Make the change. Run ALL tests — feature tests now pass, characterization tests still pass, full suite green. |
| D | Verification | Break-the-implementation check for new behavior. Also verify characterization tests catch regressions by temporarily reverting part of the change. Self-audit summary. Present for user confirmation. |
| E | Code review | Scan changed files against `harness/code_review_patterns.md`. Fix violations, re-run tests. |
| F | Reflection | Follow `harness/reflection.md`. Additionally: assess whether the touched code has better test coverage now than before the change. |
| B3 | Cleanup | Update planning docs per `harness/updatingHigherLevelDocs.md`. Change spec and reconnaissance artifacts stay committed to the branch but are removed upon merge to main (see Artifact Lifecycle). |

### Characterization tests

Characterization tests fill in gaps in test coverage for desired behaviors within the blast radius of your change. That's the whole concept.

Existing tests already protect some behaviors. Characterization tests cover the rest — the desired behaviors that nobody wrote tests for yet, but that your change could break. The change spec tells you exactly which behaviors these are: Section 5 (invariants to preserve) identifies them, and reconnaissance tells you which of those lack tests.

**Do not write characterization tests for behaviors you intend to change.** Those get feature tests. Characterization tests are only for behaviors that should survive your change unchanged.

Both types are presented together in B1 and written together, but they have different expected outcomes:

| | Feature tests | Characterization tests |
|---|---|---|
| **Purpose** | Verify new/changed behavior works | Fill test gaps for existing desired behaviors in the blast radius |
| **Expected initial result** | Fail (behavior doesn't exist yet) | Pass (behavior already exists) |
| **After implementation** | Pass | Still pass |
| **Kept permanently?** | Yes | Yes — they become regression tests for future changes |

When writing characterization tests:
- Test at the interface level (function inputs/outputs), not implementation details
- Include edge cases that the reconnaissance flagged as implicit contracts
- These tests stay in the codebase permanently — they're not scaffolding. They protect future maintainability.

### Continuous regression discipline

For brownfield changes, "run the tests" means run ALL tests, not just the ones you wrote:

- **After B1 (all tests written):** Full suite. Characterization tests pass, feature tests fail for the right reasons, everything else unchanged from B0.
- **After B2 (preparatory refactor):** Full suite. Characterization tests still pass, feature tests still fail.
- **After C (implementation):** Full suite. All tests pass, no regressions.
- **After E (code review fixes):** Full suite. Final green confirmation.

If the full suite is slow, run at minimum: your new tests + characterization tests + tests in affected modules after each step, and the full suite at B0, after C, and after E.

### Opportunistic test coverage

Every brownfield change should leave the touched code better tested than it was before. This means:

- If you touch an untested function, add characterization tests even if your change doesn't strictly require them.
- If you fix a bug, write a regression test that fails without the fix.
- If you refactor for testability, the improved structure makes it easier for future changes to add tests.

This is not about achieving coverage metrics. It's about the practical principle that code you've just read and understood is code you're uniquely positioned to test. Future sessions won't have that context.

### Artifact lifecycle

The change spec and reconnaissance document are **branch-scoped artifacts**. They are committed to the branch during development — they provide context for the session, for code review, and for any future sessions on the same branch. They are removed upon merge to main. The commit messages and PR description carry the "why" into main; the working artifacts' job is done.

---

## What the Execution Plan Does NOT Contain

- **Behaviors to test** — those are proposed during Phase A (greenfield) or B1 (brownfield), not upfront. The user may have changed their mind since the plan was written.
- **Test code or implementation code** — the plan is a roadmap, not a code dump.
- **Detailed prompt templates or API schemas** — those emerge during implementation.
- **Resolved decisions** — once the user answers the questions in Section 6, incorporate their answers into the plan and proceed. Don't carry answered questions forward.

---

## Presenting the Plan

End the execution plan with a clear prompt asking the user to confirm, adjust, or reject before you proceed. Example:

> "Does this plan look good? Would you like to adjust the scope, implementation approach, or phasing before I begin?"

Only after the user confirms should you move into Phase A (greenfield) or B0 (brownfield).
