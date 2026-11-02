# Add the big-model `heal_big` chain to AIService

Type: task
Status: resolved
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

**Built**
- `stepper/engine/ai/providers.py`: `ClaudeProvider.__init__(self, model: str = "claude-haiku-4-5-20251001")` stores `self._model`; `chat()` sends `model=self._model`. The kwargs dict is otherwise unchanged.
- `stepper/engine/ai/service.py`: `_BIG_MODEL = "claude-sonnet-5-5"`, `_TASK_CHAINS["heal_big"] = ["claude_big"]`, `_MAX_TOKENS["heal_big"] = 1024`, `"claude_big": ClaudeProvider(model=_BIG_MODEL)` in `AIService._providers`, and a `heal_big` row in the docstring table.
- `stepper/tests/unit/test_ai_service.py`: `_service()` now builds a `claude_big` double too, plus 5 new tests: the chain is `["claude_big"]`, a heal_big chat asks only `claude_big`, a failing `claude_big` raises with no cheap fallback, `AIService()._providers["claude_big"]._model == "claude-sonnet-5-5"`, and with `ANTHROPIC_API_KEY` unset `AIService().chat("x", task_type="heal_big")` raises `RuntimeError`.
- `stepper/tests/unit/test_ai_providers.py`: 3 new tests with `anthropic.Anthropic` monkeypatched to a recording client. `ClaudeProvider()._model` is still the Haiku id. `ClaudeProvider(model="m")` sends exactly `{model: "m", max_tokens: 77, messages: [...], system: "be brief"}`. The default request is exactly `{model: haiku, max_tokens: 512, messages: [...]}`, with no `system` key.

**Proof** (run after the last edit)
- `python3 -m pytest stepper/tests/unit/test_ai_service.py -q`: `21 passed`, exit 0. Includes the new heal_big tests listed above, plus the parametrized token-budget case for `heal_big` (1024, answered by the `claude_big` double).
- `python3 -m pytest stepper/tests/unit/test_ai_providers.py -q`: `24 passed`.
- `python3 -m pytest stepper/tests/unit/ -q`: `1877 passed`.
- Also passing: Build `python3 -m compileall -q stepper poms` (exit 0) and Lint `python3 stepper/main.py validate` (exit 0). Test-first commit c49c7fa failed 6 tests with `TypeError: ClaudeProvider.__init__() got an unexpected keyword argument 'model'` and KeyError on `heal_big`/`claude_big`.
- Acceptance, for reference: 2 of the 3 heal_big tests in `test_accept_heal.py` pass. The third (`test_an_embed_direct_miss_is_free_then_two_cheap_tries_then_the_big_model`) fails with `ModuleNotFoundError: stepper.brightsky.executor`, which a later ticket builds.

**Decisions**
- The model is kept on the private attribute `_model`, matching `_key`. Tests read that attribute instead of making a request.
- The ClaudeProvider class docstring still says "Claude Haiku provider". I left it as it is, because the default is still Haiku and the ticket did not ask for a docstring edit.

**Shortcuts taken**: none.

**For later tickets**
- Ticket 12: `chat(..., task_type="heal_big")` only asks `claude_big`. Without a key it raises `RuntimeError("... all providers failed ...")` and sends no request. Any test double list that is keyed by provider name has to include `claude_big`.
