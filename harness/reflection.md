# Reflection

After completing a significant task or encountering an unexpected issue, take a moment to reflect on what you learned and consider how to improve the codebase's documentation for future sessions.

---

## When to Reflect

Trigger reflection when:
- A task took longer than expected due to unclear documentation
- You encountered a bug or issue caused by undocumented assumptions
- You discovered a pattern that would help future implementations
- You had to ask the user for clarification that could have been in the docs
- You made a mistake that better guidance could have prevented
- You found a workaround that should be documented

---

## Reflection Process

### Step 1: Identify the Learning

Ask yourself:
- What went wrong, or what was harder than it should have been?
- What assumption did I make that turned out to be incorrect?
- What information was missing that would have helped?
- What pattern or anti-pattern did I discover?

### Step 2: Generalize the Insight

Convert the specific experience into a general principle:
- **Specific:** "Classification failed when the LLM returned a tag not defined in the taxonomy config"
- **General:** "Always validate LLM outputs against the configured schema before using them downstream"

### Step 3: Determine Where to Document

| Type of Learning | Where to Add |
|-----------------|--------------|
| Coding patterns, anti-patterns, style | `agent_instructions/coding_principles.md` |
| Architecture decisions, module boundaries | `planning/ARCHITECTURE.md` |
| Product requirements, scope decisions | `planning/PRD.md` |
| Implementation details, configuration | `planning/other_context.md` |
| Task sequencing, milestone dependencies | `planning/implementation_plan.md` |
| Meta-guidance for AI behavior | `agent_instructions/` (existing or new file) |

### Step 4: Propose the Update

Suggest specific text to add to the appropriate document. Be concrete:
- Include code examples for patterns/anti-patterns
- Add to existing sections where the content fits
- Create new sections only when the topic is distinct
- Update version history if the document has one

---

## Prompting the User

After significant tasks, ask the user:

> "I learned [X] during this task. Would you like me to add guidance about this to [document]? This would help future sessions avoid the same issue."

Or proactively suggest:

> "Based on what just happened, I'd recommend adding [specific guidance] to [document]. Should I make that change?"

---

## Example Reflection

**Situation:** Classification failed silently when the LLM returned tags not in the taxonomy, and the error wasn't surfaced until downstream validation.

**Learning:** LLM outputs should be validated against the configured taxonomy immediately after parsing, with clear errors logged for debugging.

**Generalization:** Always validate external/untrusted output against known contracts before propagating through the system.

**Documentation updates:**
1. Added "LLM Output Validation" section to `coding_principles.md`
2. Updated `ARCHITECTURE.md` to note that classification results are validated against taxonomy labels

---

## Benefits of Reflection

- **Prevents repeat mistakes** — Future sessions won't hit the same issues
- **Builds institutional knowledge** — The codebase becomes self-documenting
- **Improves efficiency** — Less time spent debugging known issues
- **Creates feedback loop** — Each session makes the next one better

---

## Anti-Patterns to Avoid

❌ **Over-documenting** — Don't add guidance for one-off issues unlikely to recur
❌ **Vague principles** — "Be careful with notebooks" is less useful than specific patterns
❌ **Duplicating content** — Check if guidance already exists before adding
❌ **Skipping reflection** — The value compounds over time; don't skip it to save time
