# Updating Planning Documents

When making changes to code or harness documents, consider whether corresponding updates are needed in the planning documents. Planning docs should always reflect the current state of the project — not the state at the time they were written.

---

## Cross-Document Alignment

Planning documents have a hierarchy where upstream docs drive downstream docs:

```
planning/PRD.md (what we're building)
    ↓
planning/architecture.md (how it's structured)
    ↓
planning/implementiton plan.md (step-by-step tasks)
```

### Ripple Rules

When you change **code**, check whether the change affects:
- `planning/architecture.md` — module boundaries, data models, API contracts, technology choices
- `planning/implementiton plan.md` — step scope, dependencies, or completion status
- `planning/PRD.md` — scope decisions, deferred features, or non-goals

When you change `planning/architecture.md`, check whether corresponding changes are needed in:
- `planning/implementiton plan.md` — task breakdown may need updating to match new architecture
- `planning/PRD.md` — only if the architectural change reveals a scope change

When you change `planning/implementiton plan.md`, check whether the change reflects an architectural decision that belongs in `planning/architecture.md` instead.

When you change `planning/PRD.md`, check whether corresponding changes are needed in:
- `planning/architecture.md` — new requirements may need structural decisions
- `planning/implementiton plan.md` — new features need implementation steps

### Source of Truth Hierarchy

| Document | Source of Truth For |
|----------|---------------------|
| `planning/PRD.md` | Requirements, goals, scope, success metrics |
| `planning/architecture.md` | Structure, patterns, technology choices, data models, module boundaries |
| `planning/implementiton plan.md` | Task breakdown, sequencing, dependencies, step status |

The implementation plan *implements* architectural decisions — it should not introduce new architectural choices without updating `planning/architecture.md` first.

---

## When to Update During Implementation

### After completing an implementation step

1. **Mark the step as complete** in `planning/implementiton plan.md`
2. **Update architecture if the implementation deviated** — if you made a design decision that differs from what `planning/architecture.md` describes (e.g., changed a data model, added a module, altered an API contract), update architecture to match reality
3. **Check for resolved items** — look for open questions, assumptions, or risks in the planning docs that this implementation addresses, and mark them resolved

### After a refactor

Refactors are especially likely to require planning doc updates because they change module boundaries, data models, or API contracts — all of which are documented in `planning/architecture.md`.

1. **Update `planning/architecture.md`** with the new structure
2. **Update `planning/implementiton plan.md`** if remaining steps reference the old structure
3. **Note the refactor rationale** so future sessions understand why the design changed

### After a scope change

When a feature is added, removed, or deferred:

1. **Update `planning/PRD.md`** — move features between scope/deferred/non-goals as needed
2. **Update `planning/implementiton plan.md`** — add, remove, or resequence steps
3. **Update `planning/architecture.md`** — only if the scope change affects system structure

---

## Key Principle

If you implement something that addresses a documented concern, assumption, risk, or open question, **mark it as resolved** in the relevant planning document. Stale open questions erode trust in the planning docs.
