# Exam Submission — Design Narrative

> **A note on scope:** I know this goes well beyond what was asked. I built the Stepper
> framework because I wanted to demonstrate architectural thinking — not because the exam
> required it. The four exam functions are in `exam/` and can be evaluated completely
> independently of everything else. The framework is an addition, not a substitute.
> I'm aware that in a real job, building a framework when asked for a test suite would
> be the wrong call. Here it was a deliberate choice to show how I think about design.

---

## The Thinking Behind This Solution

The exam asked for four functions and a test suite. I wrote those — but I also asked
a broader question: *what would a professional automation solution actually look like?*

The answer shaped everything. Rather than writing a collection of test scripts, I built
two complementary layers: a **pytest exam suite** that proves the required functions
work, and a **Stepper engine** that proves the same logic can be orchestrated
declaratively, extended without touching existing code, and reused across sites and
scenarios with no duplication.

They are not two versions of the same thing. They are two different perspectives on
the same problem — and they share the same POM foundation.

---

## The Two Paths

### Path 1 — The Exam Suite (`exam/`)

This is the direct answer to the exam spec. Four functions in `exam/flows.py`, each
delegating to a POM class in `poms/`. A pytest suite exercises them end-to-end
against a live browser.

```bash
cd exam
pytest tests/ -v
pytest tests/ -v --headed          # watch the browser
pytest tests/ -v --all-cases       # run all parametrised test cases
```

The exam suite is intentionally simple. Its job is to be readable, to demonstrate that
the functions behave correctly, and to be runnable by anyone in one command.

### Path 2 — The Stepper Engine (`stepper/`)

This is the answer to a different question: *what if the automation logic didn't live
in Python at all?*

The Stepper separates **what to do** from **how to do it**. A JSON workflow file
describes a sequence of named actions and their parameters. The engine resolves action
names to strategy objects, finds elements using a cascade of techniques, executes steps
with retry and reporting, and writes structured output — all without the workflow author
writing a single line of Python.

```bash
cd stepper
python main.py --workflow sites/openlibrary/workflows/ol_search_and_add.json
python main.py --workflow sites/openlibrary/workflows/ol_search_and_add.json --show
python main.py --workflow sites/openlibrary/workflows/ol_search_and_add.json \
  --vars '{"query":"Tolkien","max_year":1970,"limit":3}'
```

The same workflow runs against different data without changing a line:

```bash
pytest tests/test_workflow.py::test_data_driven -v --workflow ol_search_and_add.json --data ../poms/openLibrary/data/testdata.json --all-cases
```

Both paths hit the same `poms/` POM layer. The POM is the single source of
truth for all element knowledge. Neither the JSON workflow nor the pytest test ever
contains a CSS selector or an XPath.

---

## Why a Framework, Not Just Tests

A test script binds three concerns together: *what* to automate, *how* to find
elements, and *how* to run and report. When the site changes, you edit the script.
When you want a new scenario, you copy the script. When you want consistent reporting,
you add the same boilerplate to every file.

The Stepper pulls those concerns apart:

- **What to do** lives in a JSON workflow — readable by anyone, editable without
  touching code, composable by nesting workflows inside each other.
- **How to find elements** lives in POM `Locators` classes — one place, owned by one
  file, invisible to the workflow author.
- **How to run and report** lives in the engine — `StepRunner`, `CompositeReporter`,
  `ActionRegistry` — wired together once in `main.py` and reused by every workflow.

The result is a system where adding a new scenario means adding a JSON file.
Adding a new site means writing POM classes and registering them in two lines.
Adding a new reporter means implementing one interface and appending it to a list.
None of these require modifying existing code.

That is the framework mindset: design for change, not just for today's requirement.

---

## SOLID — Not as a Checklist, but as a Design Tool

I did not apply SOLID principles because the spec asked for them. I applied them
because each one solved a real problem I encountered while building this.

### Single Responsibility — one reason to change

Early in the design it was tempting to put element-finding logic inside the action
classes. A `ClickAction` that also knows how to resolve elements is easier to write
initially — but it means that a change to element resolution strategy forces you to
touch every action.

The solution was `ElementResolver` as a separate object, injected into actions at
runtime. Now the resolver can change its strategy (add a new technique, tune confidence
thresholds) without `ClickAction` knowing anything about it. Each class has one reason
to change, so changes stay local.

### Open/Closed — extend without touching

The most visible expression of OCP in this project is the `ActionRegistry`. To add a
new action — `drag_and_drop`, `upload_file`, a site-specific `ol_ensure_count` — you
subclass `ActionStrategy`, give it a name, and register it. Nothing else changes.
`StepRunner` already knows how to call it. The existing actions are untouched.

The same applies to reporters. `CompositeReporter` broadcasts to a list of `Reporter`
implementations. Adding Slack notifications, a database sink, or a custom HTML summary
means implementing one interface and adding one line in `main.py`. The engine has no
knowledge of what reporters exist.

This is what makes the system genuinely extensible rather than just configurable.

### Liskov Substitution — trust the contract

Every `ActionStrategy` subclass honours the same contract: given a page and a step
config, return a `StepResult`. `StepRunner` calls `.execute()` and processes the result
— it does not care whether the action navigated, clicked, ran a sub-workflow, or
benchmarked performance. Any strategy is a valid substitute for any other, as far as
the runner is concerned.

The same holds for `IBrowserDriver`. All POMs in `poms/` depend on this
interface, not on Playwright's `Page` object directly. A test double, a remote driver,
or a future CDP implementation would drop in without changing a POM class.

### Interface Segregation — small contracts, focused dependencies

`StepRunner` depends on `ActionFactory` (one method: create by name) and `Reporter`
(three methods: start, record, finish). It does not depend on a large automation
framework object that happens to also do reporting. Each boundary in the system is
defined by a small interface that captures exactly what the consumer needs — nothing
more.

### Dependency Inversion — `main.py` as the composition root

`main.py` is the only file in the project that imports concrete classes. It builds the
resolver, the registry, the reporters, and the runner — and wires them together by
passing interfaces. `StepRunner` receives an `ActionFactory` and a `Reporter`. It never
calls `import ClickAction` or `import JsonReporter`. This means the entire engine is
testable in isolation: swap the registry for a mock, swap the reporter for a spy, and
you can run the runner without a browser.

The composition root pattern is what makes DIP practical. One place knows about
concretions. Everything else knows only about abstractions.

---

## Architectural Patterns — Why Each One

**Strategy** is the backbone. Actions, resolvers, reporters, and planners are all
Strategy hierarchies. The runner, the resolver orchestrator, and the composite reporter
are all clients that work against the abstraction — they can be written and tested
without any concrete implementations existing yet.

**Template Method** keeps action implementations focused. `ActionStrategy.execute()`
handles pre-step setup, timing, error wrapping, and post-step teardown. Concrete
actions implement only `_execute()` — the interesting part. The boilerplate that would
otherwise be duplicated across sixteen action classes lives in exactly one place.

**Factory + Registry** is what makes the JSON workflow possible. A step says
`"action": "ol_collect_books"`. The registry maps that string to the right strategy
object. `StepRunner` never imports an action class — it asks the factory. This
indirection is what makes the system open for extension: register a new class, and the
engine can execute it immediately.

**Observer** decouples execution from observation. `StepRunner` notifies observers
after each step. `LoggingObserver` writes to the terminal. Other observers could post
to monitoring systems or trigger alerts. The runner does not know or care what happens
after it notifies — it just runs steps.

**Chain of Responsibility** is the element resolver cascade. When a step says
`{ "role": "button", "name": "Want to Read" }`, the resolver tries strategies in
confidence order: ARIA role, label text, visible text, CSS, XPath — stopping at the
first confident match. If no deterministic strategy succeeds, semantic scoring (MiniLM
embeddings) filters candidates by meaning. If that fails, an AI model picks from the
remaining options. No strategy knows about the others. Adding a new resolution
technique means adding a new strategy to the chain.

**Adapter** keeps the POMs clean. `PlaywrightDriver` wraps Playwright's `Page` behind
`IBrowserDriver`. Every POM calls `driver.click()`, `driver.fill()`, `driver.goto()` —
none of them import `playwright`. The automation framework is isolated to one adapter
class.

---

## What the Stepper Enables That Tests Cannot

Beyond the architecture, the Stepper unlocks capabilities that a pytest suite cannot
easily provide:

**Self-healing with step injection.** When a step fails, the engine doesn't just try to fix the
broken selector — it also diagnoses *why* the element wasn't actionable. If the element exists in
the DOM but is off-screen, the healer injects a `scroll_to` step before the original step and
retries. If the element is present but temporarily disabled, a `wait` step is injected instead.
Only `read_only=True` actions are eligible for injection — they cannot produce false-positive
fixes because they have no app-state side effects. The injection runs in a disposable
`StepRunner` with `continue_on_failure=True` on the pre-step, so the original step always runs
regardless. If the injected step doesn't resolve the issue, the full AI cascade takes over.
This means the healer can now adapt to small UI layout changes (element moved out of viewport)
as well as broken selectors — without any workflow author involvement.

**Conditional execution.** A step can carry a `when` guard — a condition evaluated
against live context state. A step that adds books only runs if books were collected.
An assertion step only runs if a count was stored. This is flow control without `if`
statements in code.

**Composable workflows.** A `run_workflow` action nests one JSON file inside another.
The login flow is defined once and reused by every workflow that needs authentication.
No copy-paste, no inheritance chain — just composition.

**Parallel execution.** A `parallel` action runs multiple read-only steps concurrently
in separate browser tabs. Three performance benchmarks that would run sequentially in
pytest run simultaneously in the Stepper, producing results in the time of the slowest
one.

**Natural language tasks.** Passing `--task` instead of `--workflow` routes the
description through `ClaudePlanner`, which translates it into `[StepConfig]` objects
and runs them through the same engine. The engine does not change — only the planner
changes. This is the Strategy pattern making a qualitatively new capability possible
with zero changes to the execution layer.

---

## How to Evaluate

To see the exam functions directly:
```bash
cd exam && pytest tests/ -v
```

To see the framework in action:
```bash
cd stepper
python main.py --workflow sites/openlibrary/workflows/ol_search_and_add.json --show
```

To see the flexibility argument in one command:
```bash
python main.py --workflow sites/openlibrary/workflows/ol_search_and_add.json \
  --vars '{"query":"Asimov","max_year":1965,"limit":2}' --show
```

To see the full architecture documented:
- [ARCHITECTURE.md](ARCHITECTURE.md) — diagrams, data flow, pattern summary
- [README.md](README.md) — project structure, all actions, all workflows, quick start
