# Let DOMSnapshotCascade.capture skip its embed_direct shortcut on request

Type: task
Status: resolved
Blocked by: —
Test first: yes
Level: 3
Touches: stepper/engine/healer/dom_snapshot.py, stepper/tests/unit/test_dom_snapshot_cascade.py

The brief's Decided line: "After the free embed_direct try has missed, the cheap and big
AI calls must see the page: DOMSnapshotCascade.capture gains an opt-in way to skip its
embed_direct shortcut and return its candidates/aria payload with content. That small
addition to the existing cascade is in scope; it is still not a new healer."

Today both places in `DOMSnapshotCascade.capture` that return
`strategy_used="embed_direct"` return `content=""`, and the heal loop captures again on
every attempt, so after an `embed_direct` miss the same empty payload would reach the AI
(`AiHealer.heal` builds its prompt from `"dom": dom.content`). Level 3: it is on the
`Sensitive:` path `stepper/engine/healer/`, and it decides what page content goes to a
paid model.

- `capture(cls, page, step: StepConfig, *, skip_direct: bool = False) -> DomPayload`.
- With `skip_direct=False` (the default) nothing changes, and every existing caller
  and test double that calls or replaces `capture(page, step)` keeps working.
- With `skip_direct=True`, both `embed_direct` returns (the lone high scorer, and the
  clear winner from `_clear_winner`) return `cls._candidates_payload(scored,
  "embed_candidates")` instead: the top `_TOP_N` candidates as JSON, `healed_cfg=None`,
  and a non-zero `token_estimate`. The scoped and aria rungs are unchanged, since they
  already carry content.
- Update the class docstring's one-line contract.

## Not in this ticket

- Passing `skip_direct=True` from the heal loop once `embed_direct` has been tried, and
  the strict heal order itself; ticket 12.
- Any change to scoring, thresholds, the cross-encoder or `_pinned_cfg`.

## Done when

- `python3 -m pytest stepper/tests/unit/test_dom_snapshot_cascade.py -q` passes, with new
  tests using the file's `fixed_scores` fixture. For the lone-high-scorer page of
  `test_a_unique_high_scoring_element_costs_no_tokens` and for a clear-winner page,
  `capture(page, step, skip_direct=True)` returns `strategy_used == "embed_candidates"`,
  `healed_cfg is None`, and `content` that parses as JSON with a non-empty `candidates`
  list holding the element the default call would have healed to.
- In the same file, the same pages with the default call still return `embed_direct`
  with `content == ""`, and every existing test passes unchanged.
- All existing tests still pass: `python3 -m pytest stepper/tests/unit/ -q`.

```check
# The conductor runs this block before review.
$ python3 -m pytest stepper/tests/unit/test_dom_snapshot_cascade.py -q
prints passed
$ python3 -m pytest stepper/tests/unit/ -q
prints passed
```

## Reference

- spec.md § Decisions ("Heal order"), § Interfaces (Engine changes)
- `stepper/engine/healer/dom_snapshot.py` `DOMSnapshotCascade.capture`,
  `_candidates_payload`, `_clear_winner`
- `stepper/tests/unit/test_dom_snapshot_cascade.py` `fixed_scores` fixture

## Answer

Work started at commit `0fb81901bc344fb2fd8fa9008d67a48a4f32da21`.

**Built**
- `stepper/engine/healer/dom_snapshot.py`: `DOMSnapshotCascade.capture(cls, page, step, *, skip_direct: bool = False)`. With `skip_direct=True`, the lone-high-scorer return and the `_clear_winner` return both become `cls._candidates_payload(scored, "embed_candidates")`. The class docstring's contract names the keyword. Scoped, aria and the ambiguous-high return are untouched.
- `stepper/tests/unit/test_dom_snapshot_cascade.py`: appended `test_skip_direct_turns_a_lone_high_scorer_into_candidates` (the page and scores of `test_a_unique_high_scoring_element_costs_no_tokens`) and `test_skip_direct_turns_a_clear_winner_into_candidates` (the `_login_form()` click page of `test_a_click_ignores_text_fields_and_heals_to_the_lone_button`). Both use `fixed_scores`. Each calls the default capture and the `skip_direct=True` capture on the same page and checks both. No existing line changed (`git diff 0fb8190` on the file shows 0 removed lines).

**Proof**
- Test-first commit `f53f573` (test file only): the file ran with `2 failed, 108 passed`, both with `TypeError: DOMSnapshotCascade.capture() got an unexpected keyword argument 'skip_direct'`.
- `python3 -m pytest stepper/tests/unit/test_dom_snapshot_cascade.py -q`: `110 passed`, exit 0. The new tests check that the skip_direct call gives `strategy_used == "embed_candidates"`, `healed_cfg is None`, `token_estimate > 0`, and a non-empty `candidates` list in which one entry, with `_score` removed, equals the default call's `healed_cfg`.
- Default path in the same tests: `strategy_used == "embed_direct"` and `content == ""` for both pages. All existing tests in the file pass unchanged.
- `python3 -m pytest stepper/tests/unit/ -q`: `1992 passed`. Build (`compileall`) exit 0, Lint (`stepper/main.py validate`) exit 0.

**Decisions**
- Passed the full `scored` list to `_candidates_payload`, as the ticket says, not `high`. `_candidates_payload` slices `[:_TOP_N]` itself. For a lone high scorer this also gives the AI the runners-up, not just the one element that already missed.
- The skip check comes before `_pinned_cfg`, so `skip_direct=True` makes no `page.locator` or `get_by_*` calls for the pin.

**Shortcuts taken**: none.

**For later tickets**
- Ticket 12: pass `skip_direct=True` to `DOMSnapshotCascade.capture` after an `embed_direct` cfg has been tried. The result is `embed_candidates` with `healed_cfg=None`, so `AiHealer.heal` goes on to the AI with `dom.content` set. The `DomPayload` docstring in `stepper/engine/healer/interfaces.py` ("empty for embed_direct") is still true, since skip_direct never returns `embed_direct`.
