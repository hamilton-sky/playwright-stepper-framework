# Add the big-model `heal_big` chain to AIService

Type: task
Status: open
Blocked by: —
Test first: yes
Level: 3
Touches: stepper/engine/ai/providers.py, stepper/engine/ai/service.py, stepper/tests/unit/test_ai_service.py, stepper/tests/unit/test_ai_providers.py

The brief's Decided line: the big-model rung "does not exist yet (AIService's heal chain
is groq, gemini, claude-haiku). Adding it as one more escalation entry in
AIService/providers is in scope; it is not a new healer." This ticket adds that entry
and nothing that calls it; when it is called is ticket 12's heal order. Level 3, because
it adds a paid model.

- **`providers.py`.** `ClaudeProvider.__init__(self, model: str =
  "claude-haiku-4-5-20251001")` stores the model, and `chat()` uses it. Keep the request
  kwargs exactly as they are built today (`model`, `max_tokens`, `messages`, `system`
  when given); only the model becomes a parameter. `is_configured` still reads
  `ANTHROPIC_API_KEY`.
- **`service.py`.**
  - Add one constant, `_BIG_MODEL = "claude-sonnet-5-5"`. Do not reuse ClaudePlanner's
    `claude-sonnet-4-20250514`: Anthropic retired it on 2026-06-15 (map.md, source line).
    Changing the planner's default is not part of this ticket.
  - Add `_TASK_CHAINS["heal_big"] = ["claude_big"]` and `_MAX_TOKENS["heal_big"] = 1024`.
  - Add `"claude_big": ClaudeProvider(model=_BIG_MODEL)` to `AIService._providers`.
  - The `heal` chain and every other chain stay unchanged. Add the `heal_big` row to the
    module docstring's chain table.
- **Tests.** `test_ai_service.py`'s `_service()` helper builds doubles for
  `("groq", "gemini", "claude")`; add `"claude_big"` so a `heal_big` test can run.

Without `ANTHROPIC_API_KEY`, `claude_big` is unconfigured and `AIService.chat(...,
task_type="heal_big")` raises `RuntimeError` without a request. That is the brief's
"without a key the loop stops at that tier".

## Not in this ticket

- Asking for `heal_big` from the healer, and the order of the rungs; ticket 12.
- Any change to `DOMSnapshotCascade` or `AiHealer`.

## Done when

- `python3 -m pytest stepper/tests/unit/test_ai_service.py -q` passes, with new tests
  showing that `_TASK_CHAINS["heal_big"] == ["claude_big"]`, that a `heal_big` chat asks
  only the `claude_big` double (never groq, gemini or claude), that
  `AIService()._providers["claude_big"]` uses model `claude-sonnet-5-5`, and that with
  `ANTHROPIC_API_KEY` unset `AIService().chat("x", task_type="heal_big")` raises
  `RuntimeError`.
- `python3 -m pytest stepper/tests/unit/test_ai_providers.py -q` passes, with new tests
  showing that `ClaudeProvider()` keeps the Haiku id, `ClaudeProvider(model="m")` sends
  `model="m"` to a stubbed client, and the other request kwargs are unchanged.
- All existing tests still pass: `python3 -m pytest stepper/tests/unit/ -q`.

```check
# The conductor runs this block before review.
$ python3 -m pytest stepper/tests/unit/test_ai_service.py -q
prints passed
$ python3 -m pytest stepper/tests/unit/test_ai_providers.py -q
prints passed
$ python3 -m pytest stepper/tests/unit/ -q
prints passed
```

## Reference

- spec.md § Decisions ("Big model id"), § Interfaces (Engine changes)
- map.md § Decisions so far (model deprecation source; the `classify` fallback for an
  unknown task type)
- `stepper/engine/ai/service.py` `_TASK_CHAINS`, `_MAX_TOKENS`, `AIService.__init__`;
  `stepper/engine/ai/providers.py` `ClaudeProvider`

## Answer
