# Add the opt-in strict heal order: a free embed_direct try, two cheap tries, then the big model

Type: task
Status: resolved
Blocked by: 04, 14
Test first: yes
Level: 3
Touches: stepper/engine/healer/interfaces.py, stepper/engine/healer/ai_healer.py, stepper/engine/runner/step_runner.py, stepper/main.py, stepper/tests/unit/test_ai_healer.py, stepper/tests/unit/test_step_runner.py, stepper/tests/unit/test_run_config.py

The brief's Decided lines govern:
- "Heal order per step is strict: exact-match (embed_direct, free) first; if it gives no
  cfg or its cfg also misses, the cheap AI tier is called; the big model is called only
  after two cheap-tier AI calls have failed for that step. An embed_direct retry never
  counts as a cheap-tier attempt, so the big model is never reached without the cheap
  tier having been tried twice."
- The cheap tier is the configured `heal` chain (groq/gemini/haiku), "so a run with only
  a Groq key still reaches the big model after two cheap failures."
- "After the free embed_direct try has missed, the cheap and big AI calls must see the
  page" (ticket 14 adds `capture(..., skip_direct=True)` for that).
- "The strict heal order is opt-in, switched on by the BrightSky executor only. Existing
  `run --heal N` behaviour and CI's heal jobs stay exactly as they are today." CI's
  keyless heal job runs `sd_heal_test` and `sd_full_heal_flow` with `--heal 2` and
  relies on today's repeated `embed_direct` tries.

Today `AiHealer.heal` returns `dom.healed_cfg` with no AI call whenever it is set, on
every attempt, so a cfg that misses is retried until the attempts run out and the AI is
never asked (map.md). This ticket adds the strict order beside it, with spec.md
§ Decisions ("Heal order") option (a), behind a switch that is off by default. Level 3,
because it decides when paid calls happen.

- **The switch.** `StepRunner(..., strict_heal_order: bool = False)`, kept on the runner
  and passed on to nothing else (replacement runners have no healer).
  `RunConfig.strict_heal_order: bool = False` in `stepper/main.py`, and `build_pipeline`
  passes `strict_heal_order=cfg.strict_heal_order` to the `StepRunner` it builds, next to
  `max_heal_attempts=`. No CLI flag sets it; only ticket 13's executors do.

- **`stepper/engine/healer/interfaces.py`.**
  - Add `FREE_TIER = "embed_direct"`.
  - `HealerStrategy.heal` gains a keyword `tried: tuple[str, ...] = ()`: the rungs
    already tried for this step and failed, oldest first.
  - Add a non-abstract `tier_for(self, dom: DomPayload, tried: tuple[str, ...]) -> str`
    returning `"healer"`. Update the class docstring's contract.
- **`ai_healer.py`.**
  - `tier_for(dom, tried)`: `"embed_direct"` when `dom.healed_cfg is not None` and
    `"embed_direct"` is not in `tried`; else `"big"` when `tried.count("cheap") >= 2`;
    else `"cheap"`.
  - `heal(..., tried=())` routes on `self.tier_for(dom, tried)`: `embed_direct` keeps
    today's zero-token fast path; `cheap` calls `self._ai.chat(..., task_type="heal")`
    as today; `big` calls `task_type="heal_big"` with the same prompt and parse. So a
    direct `heal(step, err, dom)` call behaves exactly as today.
  - Update the module docstring's cascade line.
- **`step_runner.py`, `_run_heal_loop`.** Search for `self._healer.heal(`.
  - With `strict_heal_order=False` the loop is exactly today's: `capture(self._page,
    step)` with no keyword, `heal(...)` with no `tried=` (so `tried=()` on every
    attempt, which routes as today), every attempt counts, and `healed_element` gets no
    new key.
  - With `strict_heal_order=True`:
    - Keep a per-step `tried: list[str]`. Call `DOMSnapshotCascade.capture(self._page,
      step, skip_direct=True)` once `FREE_TIER` is in `tried`, so the cheap and big rungs
      get the candidates payload with content; before that, call it as today. Then take
      `tier = self._healer.tier_for(dom, tuple(tried))` and pass `tried=tuple(tried)` to
      `heal`. When that attempt does not end in a heal (the healer raised, the replacement
      failed, or `heal_assert` failed), append `tier` to `tried`.
    - The first attempt whose tier is `FREE_TIER` does not use up one of
      `max_heal_attempts`; any later one does. So with `max_heal_attempts=3` the loop runs
      at most four times, and an iteration that raises before the tier is known still uses
      one up, so the loop always ends.
    - On a successful cascade heal, add `"tier": tier` to `healed_element`. On a heal-cache
      hit, add `"tier": "heal_cache"`.
  - In both modes nothing else changes: the cache, the visual-bridge injections,
    `_heal_succeeded` and the suggestions behave as before. `StepResult.heal_attempts`
    counts every iteration, the free one included.

## Not in this ticket

- The `heal_big` chain and its model; ticket 04.
- Choosing `max_heal_attempts=3` for BrightSky runs and reading `healed_element["tier"]`
  into the run report; tickets 05 and 13.
- The `skip_direct` option of `DOMSnapshotCascade.capture`; ticket 14. This ticket only
  passes it.
- A CLI flag for the strict order. The brief keeps `run --heal N` as it is.

## Done when

- `python3 -m pytest stepper/tests/unit/test_ai_healer.py -q` passes, with new tests
  showing that `tier_for` gives `embed_direct` for a payload with a cfg and `tried=()`,
  `cheap` for the same payload with `tried=("embed_direct",)` and for one with no cfg,
  `cheap` after one `cheap`, and `big` after two; and that `heal` with those inputs
  calls the AI with `task_type` none, `"heal"`, `"heal"` and `"heal_big"` respectively.
- `python3 -m pytest stepper/tests/unit/test_step_runner.py -q` passes, with a new
  strict-mode embed_direct-miss test: `strict_heal_order=True`, `max_heal_attempts=3`, a
  real `AiHealer` over an AI double that records each `task_type` and prompt, and
  `DOMSnapshotCascade.capture` replaced by a fake that returns an `embed_direct` payload
  (a cfg the action still fails on, `content=""`) without `skip_direct` and a
  `scoped` payload whose content holds the marker `"PAGE-CONTENT-7"` with
  `skip_direct=True`. When every replacement fails, the double records exactly
  `["heal", "heal", "heal_big"]`, each of those prompts contains `PAGE-CONTENT-7`, the
  fake saw `skip_direct=True` on every call after the first, and the step ends
  `failed`; when only the third replacement passes, it ends `healed` with
  `healed_element["tier"] == "big"`.
- In the same file, strict mode with no cfg in the payload and every replacement failing
  records `["heal", "heal", "heal_big"]`; with a cfg that works, the step heals on the
  first iteration with no AI call and `healed_element["tier"] == "embed_direct"`; and an
  AI double that raises for `heal_big` leaves the step `failed` after its two `heal`
  calls.
- In the same file, the default order is unchanged: a runner built without
  `strict_heal_order`, `max_heal_attempts=2` and an `embed_direct` payload whose cfg
  misses makes two `embed_direct` tries, no AI call, and calls `capture` with
  `(page, step)` only; with no cfg and `max_heal_attempts=3` it asks `"heal"` three
  times and never `"heal_big"`; `healed_element` has no `"tier"` key; and
  `test_max_heal_attempts_is_capped_at_three` passes unchanged. In
  `test_run_config.py`, `RunConfig().strict_heal_order is False`.
- All existing tests still pass: `python3 -m pytest stepper/tests/unit/ -q`.

```check
# The conductor runs this block before review.
$ python3 -m pytest stepper/tests/unit/test_ai_healer.py -q
prints passed
$ python3 -m pytest stepper/tests/unit/test_step_runner.py -q
prints passed
$ python3 -m pytest stepper/tests/unit/test_run_config.py -q
prints passed
$ python3 -m pytest stepper/tests/unit/ -q
prints passed
```

## Reference

- spec.md § Decisions ("Heal order", "Recording which rung healed"), § Interfaces
  (Engine changes), § Migration and compatibility
- `.github/workflows/ci.yml` (the keyless heal job that must keep working)
- map.md § Decisions so far (today's fast path; the `classify` fallback)
- `stepper/engine/runner/step_runner.py` `_run_heal_loop`;
  `stepper/engine/healer/ai_healer.py` `AiHealer.heal`
- `stepper/tests/unit/test_step_runner.py` `make_runner` and `ScriptedAction` fixtures;
  `stepper/tests/unit/test_ai_healer.py` `_ForbiddenAI`

## Answer

Work started at commit `0747cb4a29a380291ac826303f77ba808bc73a93`. Test-first commit `adcde35`.

**Built**
- `stepper/engine/healer/interfaces.py`: `FREE_TIER = "embed_direct"`. `HealerStrategy.heal(..., tried: tuple[str, ...] = ())`, and a non-abstract `tier_for(dom, tried) -> "healer"`. The class docstring's contract describes both.
- `stepper/engine/healer/ai_healer.py`: `AiHealer.tier_for` returns `embed_direct` when a cfg is set and `embed_direct` is not in `tried`, `big` when `tried.count("cheap") >= 2`, and `cheap` otherwise. `heal(..., tried=())` routes on it: `embed_direct` takes the zero-token fast path, `cheap` uses `task_type="heal"`, and `big` uses `task_type="heal_big"` with the same prompt and parse. The module docstring now lists the rungs.
- `stepper/engine/runner/step_runner.py`:
  - New keyword `StepRunner(..., strict_heal_order=False)`, stored as `_strict_heal_order` and not passed to replacement runners.
  - With the flag off, `_run_heal_loop` takes the old branch: `capture(self._page, step)`, then `heal(...)` with no `tried`.
  - With the flag on, the loop keeps a per-step `tried` list. Once `embed_direct` is in it, `capture` is called with `skip_direct=True`. The loop calls `tier_for(dom, tuple(tried))` and passes `tried=` to `heal`. The tier is appended to `tried` when the healer raises, when the replacement fails, or when `heal_assert` fails.
  - The loop counts iterations that use up an attempt (`counted`) separately from `heal_attempt`. The first `FREE_TIER` iteration is not counted. An iteration that raises before the tier is known is counted.
  - `healed_element["tier"]` holds the rung that healed, or `"heal_cache"` on a cache hit. Both are set only in strict mode.
- `stepper/main.py`: `RunConfig.strict_heal_order: bool = False`. `build_pipeline` passes `strict_heal_order=cfg.strict_heal_order` next to `max_heal_attempts=`. No CLI flag sets it.
- Tests:
  - `stepper/tests/unit/test_ai_healer.py`: parametrized `tier_for` and `heal` routing over 6 rung cases, a direct-call-without-`tried` test, and the default `tier_for == "healer"` / `FREE_TIER` test.
  - `stepper/tests/unit/test_step_runner.py`: `ElementAction`, `_TierAI` and `_FakeCapture` doubles, a `heal_world` fixture (built on `make_runner`, a real `AiHealer`, and `VisualBridge.check` patched to None), 6 strict tests, 3 default tests, and a test that the flag is off by default.
  - `stepper/tests/unit/test_run_config.py`: `RunConfig(task=...).strict_heal_order is False`.

**Proof** (fresh runs after the last edit)
- At test-first commit `adcde35`, the tests failed for the expected reasons: `13 failed` in test_ai_healer (no `tier_for`, no `tried` keyword), `7 failed` in test_step_runner (`unexpected keyword argument 'strict_heal_order'`), and test_run_config failed on `no attribute 'strict_heal_order'`. The 3 default-order tests already passed on the old code, so they pin the old behaviour.
- `python3 -m pytest stepper/tests/unit/test_ai_healer.py -q`: `31 passed`. The `tier_for` cases are: cfg with `()` gives `embed_direct`; cfg with `("embed_direct",)` gives `cheap`; no cfg gives `cheap`; one `cheap` gives `cheap`; two give `big`. `heal` with the same inputs asks the AI with task types `[]`, `["heal"]`, `["heal"]`, `["heal"]`, `["heal_big"]`.
- `python3 -m pytest stepper/tests/unit/test_step_runner.py -q`: `36 passed`.
  - Strict, embed_direct miss with every replacement failing: `task_types == ["heal","heal","heal_big"]`, every prompt contains `PAGE-CONTENT-7`, the first capture has no `skip_direct`, the other 3 captures have `skip_direct=True`, and the step ends `failed`.
  - The same where only the third AI reply works: `healed`, `tier == "big"`, `heal_attempts == 4`.
  - Strict with no cfg: `["heal","heal","heal_big"]`, `failed`.
  - Strict with a cfg that works: `healed` on iteration 1, no AI call, `tier == "embed_direct"`.
  - A `heal_big` double that raises: two `heal` calls, then `failed`.
  - A strict cache hit: `tier == "heal_cache"`.
  - Default with `max=2` and a cfg that misses: action elements `[orig, cfg, cfg]`, no AI call, each capture called as `(page, step)` with `{}` kwargs.
  - Default with no cfg and `max=3`: `["heal","heal","heal"]`.
  - A default heal has no `"tier"` key, and `test_max_heal_attempts_is_capped_at_three` passes unchanged.
- `python3 -m pytest stepper/tests/unit/test_run_config.py -q`: `26 passed`.
- `python3 -m pytest stepper/tests/unit/ -q`: `2017 passed`. Build (`compileall`) exit 0, Lint (`stepper/main.py validate`) exit 0.
- Acceptance, for reference (`plans/brightsky-verify/acceptance/test_accept_heal.py`): the engine-level tests pass (strict runner, defaults, tier_for, minimal healer). 21 others fail with `ModuleNotFoundError: stepper.brightsky.executor` and 1 with no `StepRunner.add_hook`; both belong to later tickets.

**Decisions**
- On a heal failure, `StepResult.heal_attempts` stays as before: it is set only when a step heals, so a failed step still reports 0. When a step heals it reports every iteration, including the free one, so 4 for a heal on the big rung. Setting it on failure would have changed default mode.
- In strict mode, `tier` is `None` until `tier_for` runs. A cache hit or a visual-bridge injection that breaks out of the loop never appends to `tried`. A stale cache entry falls through to the cascade in the same iteration, as it does today.
- `AiHealer.heal` routes on `tier_for`, not on `dom.healed_cfg`. So a payload with a cfg and `tried=("embed_direct",)` goes to the AI. `skip_direct` should make that case impossible in the loop.
- The default branch is the old capture → assert → heal sequence, unchanged, inside `if not strict:`. The strict branch duplicates the `heal(...)` call so that the default call never receives `tried=`.

**Shortcuts taken**: none.

**For later tickets**
- Ticket 13: `RunConfig(strict_heal_order=True, max_heal_attempts=3)` gives the full order (free + cheap + cheap + big). With `max_heal_attempts=2`, the big rung is never reached. `healed_element["tier"]` is one of `embed_direct`, `cheap`, `big` or `heal_cache`. A visual-bridge heal (scroll_to or wait injection) sets no `healed_element` at all, so read `.get("tier")` defensively.
- `heal_attempts` is 0 on a failed step in both modes.

