# Follow-ups: brightsky-verify

What the run left for later: minor findings of passing reviews, the findings a level 2 ticket passed with after 2 review rounds, and Done when checks this host could not pass. Each is a candidate for a cleanup ticket.

## 01-settle-non-current-versions (left for later)

- 1. minor /home/claude/hamilton-sky/playwright-stepper-framework/plans/brightsky-verify/map.md: "§ Decisions so far" now has two lines for the same ticket 01 decision, and they don't match. The older line, which was already there at 124eaf1, gives the skip message as `<slug> v<N> skipped: not the current version`. The new line gives `... (v<M>)`, which is what spec.md and test_accept_verify_cli.py expect. Ticket 06 could build the wrong message from the older line. Fix: delete the older line and keep the new one. (pair review)

## 02-brightsky-config-and-models (left for later)

- 1. minor stepper/brightsky/models.py: `_int` in the readers has no upper bound. `QueueItem` and `WorkflowDetail` accept `version` 10**30, which then shows up later as a `ValueError` from `RunReport` instead of a `BrightSkyResponseError` at the boundary. Pass `MAX_VERSION` as a maximum to `_int` for `version` and `currentVersion.version`. (pair review)
- 2. minor stepper/brightsky/models.py: `WorkflowDetail.from_json` accepts an empty `site` and one longer than the backend's 253-character limit (`""` and `"../../etc"` both pass). The spec's host guard later binds navigation to this value. Require a non-empty string of at most 253 characters. (pair review)
- 3. minor stepper/brightsky/models.py: `RunReport.client` is not checked (`client="admin"` goes onto the wire), so the backend would answer with a 400 instead of a `ValueError` here. Check it against the backend's `WORKFLOW_CLIENTS`, or make it a constant rather than a field. (pair review)
