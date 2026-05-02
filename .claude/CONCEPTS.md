# Two Systems, One Philosophy

*An explanation of the Stepper Framework and the Agent Architecture — and what connects them.*

---

## Part 1 — The Stepper Framework (short)

The stepper is a test automation engine where **a JSON workflow file never talks directly to a Page Object**. That separation is the entire point.

### The three layers

```
Flow   (JSON)     ← sequences steps, controls order, conditions, variables
Glue   (Python)   ← named action class, wraps one POM behavior
POM    (Python)   ← owns selectors, raw page interactions only
```

### The registry is the wall

When the engine reads a JSON step like `{ "action": "sd_login" }`, it does not import or call anything POM-related. It calls:

```
ActionRegistry.get("sd_login")
```

The registry returns the registered `GlueAction` class. That class — and only that class — knows which POM to construct and how. The JSON never crosses into the POM world. The registry is the wall.

```
JSON step
    │
    ▼
ActionRegistry  ← lookup by name string
    │
    ▼
GlueAction._execute(page, step, resolver, context)
    │
    ▼
POM(driver, url, delays, page=page, resolver=resolver)
    │
    ▼
pom.fill_username()  /  pom.click_submit()
```

### Why each layer exists

**POM** exists so that selectors live in one place. If a button moves, you change one `Locator` definition — nothing else breaks. POMs have no flow logic, no credentials, no imports from the layers above them.

**Glue** exists so that actions have names. The glue class bridges the gap between "a JSON string" and "a real page interaction." One glue class, one job. It receives `page` and `resolver`, passes them to the POM, reads params from `step.params`, stores results in `context`. That's all.

**Flow** exists so that test scenarios live outside code. A product person can read a JSON workflow and understand what it does. Conditions, loops, variable interpolation, retry — all live here, with zero knowledge of selectors or Python classes.

### The resolver injection contract

Every POM constructed inside a glue action **must** receive `page=page, resolver=resolver`. This wires in the 10-stage element resolution cascade — role → label → placeholder → text → id → css → xpath → semantic → AI pick. Without it, the POM falls back to CSS-only. The contract is non-negotiable.

### Dependency direction

```
Flow → Glue → POM       (allowed)
POM → Glue              (forbidden — reverses direction)
Flow → POM directly     (impossible — registry is the only bridge)
```

---

## Part 2 — The Agent Architecture

The agent system is a **role-based development pipeline** where 8 specialized agents collaborate to take a feature from idea to shipped code. The protocol between them is files — not function calls, not shared memory, not conversation context.

### The 8 agents

| Agent | Model | Single responsibility |
|---|---|---|
| **architect** | opus | How to build it — layers, trade-offs, design decisions |
| **planner** | sonnet | What to build — user stories, acceptance criteria, scope |
| **builder** | sonnet | Build exactly what was planned, no more |
| **reviewer** | sonnet | Find violations before they ship, never fix them |
| **tester** | sonnet | Verify each acceptance criterion passes, report gaps |
| **discoverer** | sonnet | Trace live sites, capture POM data, follow visible flows |
| **quick** | haiku | Fast lookups, 2 tool calls max |
| **orchestrator** | haiku | Sequence the pipeline, route feedback files |

### The file protocol

Each agent writes a file when its job is done. The next agent reads that file. No agent calls another directly. State lives on disk.

```
architect  → STORM_SEED.md
planner    → plans/<feature>/ (8 files)
builder    → code + PROGRESS.md
reviewer   → ARCH_FEEDBACK.md / REVIEW_FAILURES.md
tester     → TEST_FAILURES.md
quick      → RETRO.md
```

### The feedback loop system

When something goes wrong, a feedback file routes the problem to the right agent:

```
reviewer finds architectural flaw  → ARCH_FEEDBACK.md    → architect redesigns
reviewer finds implementation bug  → REVIEW_FAILURES.md  → builder fixes
builder has requirement ambiguity  → IMPL_QUESTIONS.md   → planner clarifies
builder has technical blocker      → DESIGN_QUESTIONS.md → architect resolves
tester finds failing criterion     → TEST_FAILURES.md    → builder fixes
```

A feedback file existing = issue open. Deleted = resolved. The orchestrator never advances past an open feedback file. The pipeline is self-healing without human intervention at every step.

### Model tier reasoning

Opus for the architect because design requires deep reasoning. Haiku for the orchestrator because sequencing and routing require no deep reasoning. Sonnet for everyone in between — balanced cost and capability. Every model choice is intentional.

---

## Part 3 — The Philosophical Assessment

These two systems were built years apart for different purposes — one for browser automation, one for AI-assisted development. But they converge on the same set of convictions. That convergence is not coincidence. It is a consistent philosophy expressing itself in two different domains.

### Conviction 1: Responsibility must have a boundary, not a guideline

In both systems, the separation of concerns is not a recommendation — it is enforced structurally. A JSON workflow **cannot** reach a POM because the registry is the only bridge. A builder agent **cannot** make architecture decisions because it writes to `DESIGN_QUESTIONS.md` and waits.

Most architectures say "keep concerns separate." These systems make it impossible to violate. The constraint is load-bearing. Without it, everything slowly merges toward one big blob of mixed responsibility.

### Conviction 2: The protocol between roles is more important than the roles themselves

In the stepper, the locator `Locator` instance and the `resolver=resolver` injection are the contracts at the boundary. In the agent system, the feedback files are the contracts at the boundary.

Both systems invest heavily in making the boundary explicit, typed, and checked. The roles themselves are almost interchangeable — what matters is that the handoff is clean. A POM can be rewritten without touching the glue as long as the method signatures hold. A builder can be replaced without touching the planner as long as the feedback files are written correctly.

**The protocol is the architecture. The implementation is secondary.**

### Conviction 3: Linear chains fail; feedback loops survive

A naive pipeline is a straight line: A → B → C → D. When C finds a problem that originated in A, a straight line has no path back. You either ignore the problem or break the pipeline.

Both systems solve this with structured feedback. The reviewer does not just report to the chat — it writes to a specific file that routes to the specific role that owns the problem. The tester does not "fail the build" — it writes a file that goes exactly to the builder, with enough information to fix it.

Problems are routed to their owners automatically. The pipeline does not collapse; it bends back and heals.

### Conviction 4: Cheap early catches beat expensive late fixes

The stepper's resolver cascade tries the most semantically stable strategies first (role, label) before falling back to brittle ones (CSS, XPath). You pay a small cost for every interaction to avoid large, unpredictable costs from broken selectors later.

The agent pipeline pauses after every conversation before the next one begins. A reviewer runs after every build. You pay a small cost for every stage to avoid the large cost of discovering architectural problems after five conversations of implementation.

Both systems are optimized around the same asymmetry: **catching something early is almost always cheaper than fixing it late.**

### Conviction 5: Files outlive context

The stepper stores its entire state in JSON files and Python classes — nothing lives in memory between test runs. The agent system stores its entire state in plan files and feedback files — nothing lives in conversation context between agent spawns.

This makes both systems **resumable**. A test run interrupted halfway through can restart from where it stopped. A feature pipeline interrupted at stage 3 can resume at stage 3. Any agent can be replaced without restarting the whole pipeline.

Both systems treat durability as a first-class design requirement, not an afterthought.

---

## The through-line

The stepper and the agent architecture are the same answer to the same question:

> *How do you build a complex system where multiple independent units collaborate reliably, failures are caught early, and no single unit carries too much responsibility?*

The answer, expressed twice:

1. Give each unit exactly one job.
2. Make the boundary between units explicit and enforced — not advisory.
3. Route problems back to their owners through a structured protocol.
4. Catch things early, cheaply, before the next stage begins.
5. Store state on disk so the system survives any interruption.

The domain is different. The vocabulary is different. The conviction is identical.

---

## Part 4 — The Shape

The shape is a **one-way spine with precision-routed return paths.**

It has three defining geometric properties:

### 1. Narrow nodes

Every unit in both systems does exactly one thing. Not "roughly one thing" or "mostly one thing." One job. This makes each node **thin** — small surface area, minimal exposure. When something breaks, it breaks in one place, owned by one unit.

Most systems have fat nodes. Fat nodes are where bugs hide.

### 2. Explicit joints

The connections between nodes are not open surfaces — they are **named contracts**. The registry. The feedback file. The `Locator` instance. The `resolver=resolver` injection. You cannot pass something through without naming it, typing it, making it visible.

In most systems, layers bleed into each other gradually — a little CSS leaks into the flow, a little flow logic creeps into the POM. The bleeding is invisible until it is catastrophic. Named joints make the boundary visible and checkable.

### 3. Typed return paths

This is what makes the shape unusual. Most pipelines are a straight line — if something goes wrong at stage 4, you stop. There is no path back.

This shape has return paths, but they are **precise**. Not "failure goes back to the start." Not "broadcast an error." `ARCH_FEEDBACK` goes to the architect specifically. `IMPL_QUESTIONS` goes to the planner specifically. A resolver failure falls back through exactly the cascade, not randomly.

Problems travel back to their **exact owner**, along labeled paths.

### The shape in one image

```
 ┌──────┐         ┌──────┐         ┌──────┐
 │  A   │──────►  │  B   │──────►  │  C   │
 └──────┘         └──────┘         └──────┘
    ▲                 ▲
    │ (typed)         │ (typed)
    └── if A broke ───┘── if B broke
```

Not a loop. Not a tree. Not a mesh. A **directed spine where every node is thin, every joint is named, and every failure travels back along a labeled path to the node that owns it.**

**The shape is: clarity made structural.**
