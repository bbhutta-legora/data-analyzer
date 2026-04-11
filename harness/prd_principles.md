
⸻

1. Start with the problem, not the solution

Anchor everything in a clear problem statement.
	•	Who is experiencing the problem?
	•	What are they trying to do?
	•	Why does this matter now?

If you can’t explain the problem in a few sentences, the rest of the PRD will wobble.

⸻

2. Be explicit about goals and non-goals

Clarity comes as much from what you won’t do as what you will.
	•	Goals define success
	•	Non-goals prevent scope creep and misalignment

This is especially helpful for engineering and design decisions later.

⸻

3. Write for a smart reader who wasn’t in the room

Assume the reader is intelligent but lacks context.
	•	Avoid shorthand, tribal knowledge, or “as discussed”
	•	Define terms and assumptions
	•	Make decisions and tradeoffs explicit

A great PRD survives being read weeks later by someone new.

⸻

4. Focus on user value, not feature lists

Frame requirements around outcomes and behaviors:
	•	“User can accomplish X in Y time”
	•	“System prevents Z failure case”

This keeps the document from becoming a checklist of UI components.

⸻

5. Make requirements testable

If you can’t verify it, it’s not a requirement.
	•	Use clear acceptance criteria
	•	Avoid vague language like “fast,” “intuitive,” or “seamless” without definition
	•	Tie requirements to observable behavior or metrics

⸻

6. Separate what from how

PRDs should define what needs to be achieved, not over-prescribe how to build it.
	•	Leave room for engineering and design expertise
	•	Call out constraints explicitly if they exist (legal, technical, time)

Exceptions are fine—just label them as such.

### PRD vs Architecture examples

| Belongs in PRD | Belongs in Architecture |
|----------------|------------------------|
| "paragraph_id must be stable and deterministic" | "paragraph_id is derived from Word's w14:paraId attribute" |
| "error handling: handle gracefully" | "retry once with exponential backoff, then include error marker" |
| "auto-incremented version strings" | "version state file maps content hashes to version numbers" |

**Test:** If a requirement could be satisfied by multiple implementations, keep it abstract in the PRD and defer the mechanism to ARCHITECTURE.md.

⸻

7. Use structure to reduce cognitive load

Good structure > more words.
	•	Clear sections
	•	Scannable headings
	•	Tables or bullet points where appropriate

People rarely read PRDs top-to-bottom in one go.

⸻

8. Make assumptions and risks visible

Every product decision has unknowns.
	•	List key assumptions
	•	Call out risks and open questions
	•	Note dependencies

This builds trust and invites early challenge instead of late surprises.

⸻

9. Tie it to success metrics

Explain how you’ll know it worked.
	•	Quantitative where possible (adoption, time saved, error rate)
	•	Qualitative where needed (user feedback, usability signals)

This closes the loop between delivery and impact.

⸻

10. Treat the PRD as a living document

A PRD isn't a contract carved in stone.
	•	Version it
	•	Update it when decisions change
	•	Capture rationale for major changes

Staleness kills credibility fast.

⸻

11. Frontend PRDs: Wireframes vs Implementation

When writing frontend PRDs, UI wireframes (ASCII mockups, sketches, Figma links) belong in the PRD because they describe **what the user sees**—the interface contract.

Move these to a separate architecture document:
	•	Technology stack decisions (Vue, React, etc.)
	•	Component breakdown and naming
	•	API endpoint specifications
	•	Data flow diagrams
	•	State management approach
	•	Build/deployment configuration

### Frontend PRD vs Architecture examples

| Belongs in PRD | Belongs in Architecture |
|----------------|------------------------|
| UI wireframes showing layout | Component tree and naming |
| "User clicks row to expand details" | "CaseRow emits expand event, CaseDetail renders inline" |
| "Filters by status and classification" | "FilterBar uses dropdown components with v-model binding" |
| "Save persists to JSON file" | "PUT /api/files/{filename} with full JSON body" |

**Test:** If removing the detail would change what engineers build *for the user*, it belongs in the PRD. If it only changes *how* they build it, it belongs in architecture.