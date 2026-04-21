# NL Workflow Compiler — Flow Diagram

## Compile Flow (runs once, pays AI tokens)

```
CLI: python stepper/main.py --compile "intent" --site saucedemo
        │
        ▼
main.py: compile_workflow(args)
        │  build_default_registry()
        │  register_all_sites()
        │  SITE_CONFIGS["saucedemo"] → base_url
        │
        ▼
NLCompiler.compile(intent, base_url, output_path)
        │
        ├─ 1. async_playwright() → browser → page
        │       │
        │       ▼
        │  page.goto(base_url)
        │  page.accessibility.snapshot()
        │       │
        │       ├─ empty? → raise CompileError
        │       └─ >200 nodes? → truncate + warn
        │
        ├─ 2. ActionSchemaExtractor.extract(registry)
        │       → {action_name: {description: ...}}
        │
        ├─ 3. PromptBuilder.build(intent, aria_tree, action_schema)
        │       → system_prompt (cfg rules + action list)
        │       → user_prompt  (ARIA JSON + intent)
        │
        ├─ 4. AIService.chat(user_prompt, task_type="compile", system=system_prompt)
        │       │
        │       ├─ GroqProvider.chat()  ← tried first (cheapest)
        │       │       fail? ──►
        │       ├─ GeminiProvider.chat() ← fallback
        │       │       fail? ──►
        │       └─ ClaudeProvider.chat() ← last resort
        │               fail? → RuntimeError
        │
        ├─ 5. OutputParser.parse(raw_response, registry)
        │       │
        │       ├─ strip markdown fences
        │       ├─ json.loads()
        │       │       fail? → CompileError (raw shown)
        │       ├─ validate action names → warn unknown
        │       └─ return list[dict] steps
        │
        └─ 6. write JSON to output_path (mkdir if needed)
                │
                ▼
        "Workflow saved to: ..."
        "Run it with: python stepper/main.py --workflow ..."
```

---

## Execute Flow (runs every time, zero AI tokens)

```
CLI: python stepper/main.py --workflow compiled.json
        │
        ▼
JsonFilePlanner.plan() → list[StepConfig]
        │
        ▼
StepRunner.run(steps)
        │  for each step:
        │
        ├─ ActionRegistry.get(step.action)
        │
        ├─ GlueAction._execute(page, step, resolver, context)
        │       │
        │       ▼
        │  POM._resolve_and_click_any(cfg_list)
        │       │
        │       ▼
        │  ElementResolver cascade
        │       │
        │       ├─ Phase 1: RoleResolver(role, name)  ← unique match → act
        │       ├─ Phase 1: LabelResolver(label)      ← unique match → act
        │       ├─ Phase 1: CssResolver(css)          ← fallback
        │       │
        │       ├─ Phase 2: SemanticFilter (MiniLM)   ← 0 or 2+ from Phase 1
        │       │
        │       └─ Phase 3: AI Pick (Groq→Gemini→Claude) ← 2+ from Phase 2
        │
        └─ [if --heal N and step fails]
                │
                └─ AiHealer.suggest_fix() → patched step → retry
```

---

## Component Legend

| Symbol | Meaning |
|--------|---------|
| `NLCompiler` | Orchestrates compile: browser + ARIA + AI + save |
| `PromptBuilder` | Assembles system + user prompts with cfg rules |
| `OutputParser` | Parses + validates AI JSON response |
| `AIService` | Routes to Groq → Gemini → Claude by task type |
| `ActionSchemaExtractor` | Reads registry docstrings → action list for prompt |
| `ElementResolver cascade` | Deterministic resolution at execute time (no AI unless Phase 3) |
| `AiHealer` | Fires only when a locator breaks during execution |
