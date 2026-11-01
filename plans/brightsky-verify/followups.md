# Follow-ups: brightsky-verify

What the run left for later: minor findings of passing reviews, the findings a level 2 ticket passed with after 2 review rounds, and Done when checks this host could not pass. Each is a candidate for a cleanup ticket.

## 01-settle-non-current-versions (left for later)

- 1. minor /home/claude/hamilton-sky/playwright-stepper-framework/plans/brightsky-verify/map.md: "§ Decisions so far" now has two lines for the same ticket 01 decision, and they don't match. The older line, which was already there at 124eaf1, gives the skip message as `<slug> v<N> skipped: not the current version`. The new line gives `... (v<M>)`, which is what spec.md and test_accept_verify_cli.py expect. Ticket 06 could build the wrong message from the older line. Fix: delete the older line and keep the new one. (pair review)
