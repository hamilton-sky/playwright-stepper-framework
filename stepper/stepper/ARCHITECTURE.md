**Stepper Architecture (Framework)**
```
src
├─ interfaces.py
│  ├─ StepConfig / StepResult / ExecutionContext
│  ├─ ActionStrategy / ResolverStrategy
│  └─ ReporterStrategy
│
├─ actions/
│  ├─ factory.py
│  └─ strategies.py  (click/fill/assert/paginate/etc.)
│
├─ resolvers/
│  ├─ element_resolver.py  (cascade orchestrator)
│  ├─ strategies.py        (role/label/text/css/xpath/etc.)
│  └─ ai_pick_resolver.py  (AI disambiguation)
│
├─ runner/
│  ├─ step_runner.py  (executes steps)
│  ├─ api.py          (public pipeline)
│  └─ when_eval.py    (conditional logic)
│
├─ reporter/
│  └─ reporters.py (Allure/JSON/console, etc.)
│
└─ workflows/
   └─ *.json (step definitions)
```

**Core flow**
```
workflow.json
   → StepRunner
     → ActionStrategy.execute()
       → ElementResolver.resolve()  (optional)
         → Playwright Page
```
