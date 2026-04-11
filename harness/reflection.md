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
- **Specific:** "LLM response parsing broke when the model wrapped JSON in code fences with trailing prose"
- **General:** "Always strip code fences before parsing LLM JSON responses, and don't anchor the regex to end-of-string"

### Step 3: Determine Where to Document

| Type of Learning | Where to Add |
|-----------------|--------------|
| Coding patterns, anti-patterns, style | `harness/coding_principles.md` |
| Framework-specific gotchas (FastAPI, LLM, asyncio) | `harness/framework_patterns.md` |
| Architecture decisions, module boundaries | `planning/architecture.md` |
| Product requirements, scope decisions | `planning/PRD.md` |
| Task sequencing, milestone dependencies | `planning/implementiton plan.md` |
| Meta-guidance for AI behavior | `harness/` (existing or new file) |

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

**Situation:** LLM response parsing broke silently when the model returned JSON wrapped in code fences with trailing prose after the closing fence.

**Learning:** LLM JSON responses must be stripped of code fences before parsing, and the regex must not anchor to end-of-string since the model appends trailing content non-deterministically.

**Generalization:** Always validate and sanitize external/untrusted output against known contracts before propagating through the system.

**Documentation updates:**
1. Added "Handling JSON Responses" section to `harness/framework_patterns.md`
2. Updated `planning/architecture.md` to note the LLM response parsing contract

---

## Benefits of Reflection

- **Prevents repeat mistakes** — Future sessions won't hit the same issues
- **Builds institutional knowledge** — The codebase becomes self-documenting
- **Improves efficiency** — Less time spent debugging known issues
- **Creates feedback loop** — Each session makes the next one better

---

## Anti-Patterns to Avoid

- **Over-documenting** — Don't add guidance for one-off issues unlikely to recur
- **Vague principles** — "Be careful with LLM output" is less useful than specific patterns
- **Duplicating content** — Check if guidance already exists before adding
- **Skipping reflection** — The value compounds over time; don't skip it to save time
