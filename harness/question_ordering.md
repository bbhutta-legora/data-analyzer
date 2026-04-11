Clarify any points that are unclear in the document or code. 

When asking questions, ask only one question at a time.

Ask the most high leverage / most upstream question to the user, meaning the question whose answer influences the answers to other questions.

When asking a question, present to the user the decision that has to be made on the question, including all of the information that is needed to make a high quality decision.

If you give options on the decision that has to be made, give the pros and cons of each option.

---

## Identifying High-Leverage Questions

Focus questions on decisions that:
- **Change the data model or API contract** (e.g., save model, validation rules, endpoint design)
- **Affect multiple components or flows** (e.g., routing approach, state management strategy)
- **Create long-term constraints** (e.g., free-text vs. constrained inputs, atomic vs. partial saves)
- **Block implementation without an answer** (e.g., which persistence model to use)
- **Have significant trade-offs** (e.g., flexibility vs. consistency, safety vs. speed)

Make reasonable defaults or defer questions for:
- **UI patterns that follow established conventions** (e.g., stacked vs. tabbed layout when conventions exist)
- **Cosmetic or layout choices** (e.g., exact spacing, colors within a design system)
- **Implementation details with clear "standard" solutions** (e.g., which specific diff library when several are equivalent)
- **Minor UX details** that don't affect the architecture or data model

**Example high-leverage questions:**
- "Should classification be free-text or taxonomy-constrained?" (affects validation, filtering, data quality)
- "Should saves be atomic or partial?" (affects error handling, state management, UX)
- "Should we use hash mode or history mode routing?" (affects backend config and deployment)

**Example lower-leverage (can default):**
- "Should before/after/diff be stacked or tabbed?" (follow PRD wireframes or common patterns)
- "Should tags use chips or comma-separated input?" (either works; pick simplest)
- "Should we use vue-diff or diff2html?" (both solve the problem; evaluate during implementation)