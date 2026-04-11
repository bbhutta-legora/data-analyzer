We are only building a prototype here, so we do not need to pay special attention to reliability, scalability, or security. 

Keep the overall architecture simple. Stick to a monorepo for simpler apps or a layered architecture for more complex ones. Do not do service based architectures or event-driven architectures. 

Observability will be paramount for our ability to move quickly, so we should pay special attention to making robust unit, integration and functional tests. 

Ease of trace review is a top priority. Operation logs and execution traces should be structured for human readability and quick debugging. 

Avoid creating abstractions until you have 3+ concrete use cases. Note that this goes against strict enforcement of the DRY principle. 

Keep module interfaces simple. When starting out, prefer deep modules that unify business logic over many shallow modules that have to be connected for one action. Modules in this context can be functions, methods, modules, classes, or packages/dependencies. Note that this generally goes against strict enforcement of the Single Responsibility Principle. Only break out a function from a deep module where you are creating an abstraction for it per the above note regarding 3+ uses. 

Have very strict separation of concerns, with clear boundaries between layers. 

Respect the YAGNI principle throughout. 

When analyzing legacy systems for insight, focus on extracting **patterns and wisdom** rather than porting code directly. Ask "what can we learn from this?" not "what code can we reuse?" Complex legacy patterns may inform design decisions without being directly implemented. The prototype should remain simple.

When choosing technologies (language, runtime, frameworks), identify the **most technically demanding operation** in the pipeline and evaluate libraries for that operation first. Let that analysis inform broader technology choices. For example, if the core task is parsing Word XML with namespaces, the quality of XML libraries should drive the language decision.

The ARCHITECTURE.md file is the source of truth for all archiectural decsisions and features that we are choosing for the codebase. We should record all of the decisions that were made, but don't have to provide extensive reasoning as to why those decisions were made. 

---

## Canonical identity layer (do this first)

When designing a pipeline that transforms documents + edits, decide the **unit of change** and the **canonical ID strategy** upfront.

- If the pipeline requires stable identity across structural edits (insert/delete/split/merge), IDs must come from an **authoritative structural representation** (e.g., WordprocessingML `w14:paraId`), or the inputs must include a **lossless mapping** for newly created units.
- Do not assume derived artifacts (e.g., JSON “operations + base document”) preserve identity unless:
	- every operation references an existing unit ID, and
	- inserted units have a deterministic ID rule or an explicit ID provided.

Default heuristic:

- Need stable paragraph IDs across inserts/deletes → start from WordprocessingML and use `w14:paraId` as `paragraph_id`.
- Starting from JSON ops without new-unit IDs → expect identity gaps for inserts unless you accept generated IDs.