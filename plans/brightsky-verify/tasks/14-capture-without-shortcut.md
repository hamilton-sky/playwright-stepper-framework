# Let DOMSnapshotCascade.capture skip its embed_direct shortcut on request

Type: task
Status: open
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
