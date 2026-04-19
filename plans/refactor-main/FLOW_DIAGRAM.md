# Refactor main.py — Flow Diagram

## Before Refactor: run() as God Function

```
main()
  │
  └─► asyncio.run(run())
            │
            ├─ [settings try/except]      ← DUPLICATED in _run_data_rows()
            ├─ [resolver construction]    ← DUPLICATED in _run_data_rows()
            ├─ [reporter construction]
            ├─ [browser launch]           ← DUPLICATED in _run_data_rows()
            ├─ [hardcoded OL imports]     ← OCP violation
            ├─ [TEMPORAL COUPLING note]
            └─ runner.run(steps)
```

---

## After Refactor: Orchestration Only

```
main()
  │
  └─► asyncio.run(run())
            │
            ├─ _load_settings_safe()
            │       └─► (use_visual_ai, slow_mo, browser, storage_path)
            │
            ├─ _build_resolver(use_visual_ai)
            │       └─► ElementResolver
            │               │
            │               ├─ Phase 1: RoleResolver / LabelResolver / …
            │               ├─ Phase 2: SemanticFilter (MiniLM)
            │               └─ Phase 3: AI Pick (Groq → Gemini → Claude)
            │
            ├─ _build_reporters(label, browser, headless, root)
            │       └─► CompositeReporter
            │               ├─ ConsoleReporter
            │               ├─ JsonReporter
            │               ├─ TestReportReporter
            │               └─ AllureReporter
            │
            ├─ _launch_browser(pw, browser, headless, slow_mo)
            │       └─► browser instance (chromium / firefox / webkit)
            │
            ├─ _register_all_sites(registry, screenshots_dir)
            │       │  glob: sites/*/register.py
            │       ├─ sites/openlibrary/register.py  → register(registry)
            │       ├─ sites/saucedemo/register.py    → register(registry)
            │       └─ sites/phptravels/register.py   → register(registry)
            │                                  │
            │                                  └─► ActionRegistry.register(…)
            │
            ├─ [_runner_ref = []]
            ├─ RunWorkflowAction(lambda: _runner_ref[0].run)
            ├─ StepRunner(…)
            ├─ _runner_ref.append(runner)
            │
            └─ runner.run(steps)
```

---

## Data-Driven Path (_run_data_rows)

```
main() ──► _run_data_rows(rows, cli_vars, args)
                │
                ├─ _load_settings_safe()      ← same helper as run()
                ├─ _build_resolver(…)         ← same helper as run()
                ├─ _launch_browser(pw, …)     ← same helper as run()
                │
                └─ for row in rows:
                        └─► run(…, resolver=resolver, _browser=browser)
                                │
                                └─ (skips _build_resolver, _launch_browser
                                    because resolver and _browser injected)
```

---

## Site Registration Discovery

```
_register_all_sites(registry, screenshots_dir)
        │
        └─ glob("sites/*/register.py")
                │
                ├─► sites/openlibrary/register.py
                │         └─ register(registry, screenshots_dir)
                │                   ├─ OLSearchPage.register(registry)
                │                   ├─ OLDetailPage.register(registry, …)
                │                   ├─ OLReadingListPage.register(registry)
                │                   └─ OLLoginPage.register(registry)
                │
                ├─► sites/saucedemo/register.py
                │         └─ register(registry, screenshots_dir)
                │                   └─ SDLoginPage.register(registry) …
                │
                └─► sites/phptravels/register.py
                          └─ register(registry, screenshots_dir)
                                    └─ PTLoginPage.register(registry) …
```

---

## Component Legend

| Symbol | Meaning |
|--------|---------|
| `run()` | Main async entry point — orchestration only after refactor |
| `_load_settings_safe()` | Settings loading with fallback defaults |
| `_build_resolver()` | ElementResolver construction with optional AI client |
| `_build_reporters()` | All four reporters wired into CompositeReporter |
| `_launch_browser()` | Playwright browser launch with anti-detection args |
| `_register_all_sites()` | Auto-discovers and calls each site's register() |
| `_runner_ref` | Mutable cell; breaks RunWorkflowAction temporal coupling |
