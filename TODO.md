# TODO — Harness & CI Pipeline Improvements

## CI Pipeline: Restructure code_review_patterns.md into 3-tier pipeline

### Tier 1 — Automated (scripts, run on every push/PR)
- [ ] Configure ruff for Python backend with rule sets F, B, S, PD, C90 (bugs, security, pandas, complexity)
- [ ] Configure ESLint + tsc --noEmit for TypeScript frontend
- [ ] Configure unit test runs — pytest (backend) + vitest (frontend)
- [ ] Start with minimal ruff rules (F, B, S, PD, C90), expand over time based on false-positive rate

### Tier 2 — Semi-automated (tool flags candidates, LLM agent adjudicates)
- [ ] Error handling patterns (original check #2)
- [ ] Single source of truth violations (original check #4)
- [ ] Naming consistency (original check #6)
- [ ] Test coverage gaps (original check #18)
- [ ] Dead code detection (original check #16)

### Tier 3 — Judgment / LLM review (structured prompts, reasoning required)
- [ ] Architecture fit
- [ ] Security model review
- [ ] UX coherence
- [ ] PRD traceability
- [ ] Other checks requiring judgment (#1, #3, #7, #9, #10, #11, #12, #15, #19)

### Cross-cutting checks
- [ ] Dead type fields (type defined but never populated at runtime)
- [ ] PRD traceability (every acceptance criterion has endpoint + component + test)
- [ ] SSE/API contract symmetry (backend emits ↔ frontend parses ↔ store populates ↔ component renders)

### CI workflow
- [ ] Create .github/workflows/ci.yml wiring Tier 1 checks to run on push/PR
- [ ] Restructure code_review_patterns.md from flat 20-item checklist into 3-tier pipeline document

## Design Decisions (settled)
- [x] Auto-fix, not block — all tiers fix and commit to the PR branch. Tier 1 uses --fix flags (ruff --fix, eslint --fix). Anything Tier 1 can't auto-fix (type errors, test failures) escalates to LLM agent to fix and commit. Nothing blocks the pipeline.
- [x] Descoped from CI: E2E tests, performance benchmarks, cross-platform builds, most integration tests
- [x] Rate limiting is an architecture decision, not a CI concern — left outside pipeline scope

## Harness Document Updates
- [ ] Update implementation_plan_principles.md to require README.md as a scaffolding step (gap #1 — not a CI concern, belongs in project setup)
- [ ] Require full markdown wireframes as part of the PRD — every user-facing screen must have a text-based wireframe before implementation begins
- [ ] Consider trimming PRD prose in favor of wireframes — wireframes may communicate intent more precisely and concisely than written descriptions, reducing PRD length
- [ ] Rework the implementation plan so the agent can use it to sequence its own work — the plan should be structured as actionable steps the agent follows, not just a human-readable checklist

## General Agent Pattern
- [ ] Add convergent multi-pass review pattern to harness: agent re-prompts the same review with an accumulating exclusion list until 0 new findings returned. LLM finds issues (structured JSON array), code decides when to stop (len == 0), adversarial framing ("find what the previous pass missed"). Max 5 passes safety cap. Applies to any coding agent review task.
