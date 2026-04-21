# NL Workflow Compiler — Edge Cases

## Category 1: AI Response Errors

### EC-1.1: AI returns malformed JSON
- **Trigger**: Model wraps response in markdown fences or adds explanation text
- **Current behavior**: JSON parse fails
- **Expected behavior**: OutputParser strips fences, retries parse; if still invalid, raises with raw response in message
- **Handled in**: Phase 2 — OutputParser._strip_and_parse()

### EC-1.2: AI returns empty steps array
- **Trigger**: Intent too vague or ARIA tree too sparse
- **Expected behavior**: Raise `CompileError("AI returned 0 steps — intent may be too vague")`
- **Handled in**: Phase 2 — OutputParser.validate()

### EC-1.3: AI generates unknown action names
- **Trigger**: Model hallucinates action names not in registry
- **Expected behavior**: OutputParser logs a WARNING per unknown action, includes step in output anyway (self-healing may fix at runtime)
- **Handled in**: Phase 2 — OutputParser.validate()

### EC-1.4: All AI providers fail
- **Trigger**: No API keys configured or all rate-limited
- **Expected behavior**: Clear error: "compile task failed — check GROQ_API_KEY / ANTHROPIC_API_KEY in .env"
- **Handled in**: Phase 1 — AIService raises RuntimeError; NLCompiler catches and re-raises with guidance

## Category 2: Browser / Page Issues

### EC-2.1: ARIA snapshot is empty
- **Trigger**: Page didn't load (network issue, wrong base URL)
- **Expected behavior**: NLCompiler raises before calling AI: "ARIA snapshot empty — page may not have loaded"
- **Handled in**: Phase 2 — NLCompiler.compile() checks snapshot result

### EC-2.2: ARIA tree exceeds 200 nodes
- **Trigger**: Complex pages (e.g., large SPA with many interactive elements)
- **Expected behavior**: Truncate to first 200 nodes, log WARNING with node count
- **Handled in**: Phase 2 — NLCompiler._snapshot()

### EC-2.3: Page requires login before useful ARIA tree is available
- **Trigger**: Site shows login wall at base URL (phpTravels, some OpenLibrary pages)
- **Expected behavior**: v1 limitation — document in error message: "Compile snapped login page only. If you need post-login elements, add a login step first."
- **Handled in**: Phase 2 — warning log; v2 will add --compile-after-login

## Category 3: Output / File Issues

### EC-3.1: Output path parent directory does not exist
- **Trigger**: User passes custom `--output` path with missing parent
- **Expected behavior**: NLCompiler creates parent dirs with `mkdir(parents=True)`
- **Handled in**: Phase 3 — main.py / NLCompiler.save()

### EC-3.2: --compile used with --workflow or --task simultaneously
- **Trigger**: User passes conflicting flags
- **Expected behavior**: argparse error: "Cannot combine --compile with --workflow or --task"
- **Handled in**: Phase 3 — main.py argument validation

### EC-3.3: --compile without --site
- **Trigger**: User forgets --site
- **Expected behavior**: argparse error: "--site is required with --compile"
- **Handled in**: Phase 3 — main.py argument validation

## Known Limitations (v1)
- Single-page ARIA snapshot only — multi-page flows compile from intent alone, not from each page's live tree
- No --compile-after-login support (v2 item)
- Compiled JSON is not automatically version-controlled — user manages the file
