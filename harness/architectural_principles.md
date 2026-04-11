We are only building a prototype here, so we do not need to pay special attention to reliability, scalability, or security. 

Keep the overall architecture simple. Stick to a monorepo for simpler apps or a layered architecture for more complex ones. Do not do service based architectures or event-driven architectures. 

Observability will be paramount for our ability to move quickly, so we should pay special attention to making robust unit, integration and functional tests. 

Ease of trace review is a top priority. Operation logs and execution traces should be structured for human readability and quick debugging. 

Avoid creating abstractions until you have 3+ concrete use cases. Note that this goes against strict enforcement of the DRY principle. 

Keep module interfaces simple. When starting out, prefer deep modules that unify business logic over many shallow modules that have to be connected for one action. Modules in this context can be functions, methods, modules, classes, or packages/dependencies. Note that this generally goes against strict enforcement of the Single Responsibility Principle. Only break out a function from a deep module where you are creating an abstraction for it per the above note regarding 3+ uses. 

Have very strict separation of concerns, with clear boundaries between layers. 

Respect the YAGNI principle throughout. 

When analyzing legacy systems for insight, focus on extracting **patterns and wisdom** rather than porting code directly. Ask "what can we learn from this?" not "what code can we reuse?" Complex legacy patterns may inform design decisions without being directly implemented. The prototype should remain simple.

When choosing technologies (language, runtime, frameworks), identify the **most technically demanding operation** in the pipeline and evaluate libraries for that operation first. Let that analysis inform broader technology choices. For example, in this project, sandboxed execution of arbitrary LLM-generated Python code drove the decision to keep the backend in Python with in-process `exec()`.

The `planning/architecture.md` file is the source of truth for all architectural decisions and features that we are choosing for the codebase. We should record all of the decisions that were made, but don't have to provide extensive reasoning as to why those decisions were made.
