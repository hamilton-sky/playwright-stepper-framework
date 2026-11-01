# Run the bar end to end

Type: task
Status: open
Blocked by: 02, 03, 04, 05, 06, 07, 08, 10, 11, 12, 13, 14, 15
Test first: no
Level: 1

Prove the map's bar. Change no code. If something fails, write it under `## Answer

Not resolved (attempt 2): the manual bar is blocked by this host's network, not by the code. Work started at `613e6b34d5b3f99c0590ce88bc9d69c93f4b3b54`; no code changed.

**Step 1, unit bar: passes.** `python3 -m pytest stepper/tests/unit/ -q` printed `2177 passed in 38.00s`, exit 0. The test for each bar item (these 10 named tests plus `test_brightsky_workflow_file.py`, run on their own: `30 passed`):
- mapping per target kind: `stepper/tests/unit/test_brightsky_mapping.py::test_target_kinds` (parametrised), plus `test_the_pilot_maps_to_navigate_fill_click_click`;
- full pass with one idempotency key: `test_brightsky_verify.py::test_a_full_pass_posts_one_passed_report_with_one_key_and_no_proposal` (and `test_each_run_gets_its_own_idempotency_key`);
- missing element, then heal in the brief's order, then proposal (source and note) and a failed report: `test_brightsky_heal_loop.py::test_an_embed_direct_heal_is_reported_failed_then_proposed_from_stepper` and `test_a_missed_embed_direct_then_two_cheap_misses_heal_on_the_big_model`;
- missing env exits 3: `test_brightsky_cli.py::test_a_missing_variable_exits_3_with_no_traceback_and_no_client`;
- 5xx retried once, 4xx not: `test_brightsky_client.py::test_a_503_then_a_200_makes_two_calls_with_one_recorded_sleep`, `test_two_503s_raise_brightsky_http_error_503_after_two_calls`, `test_a_4xx_raises_after_exactly_one_call_with_no_sleep`.

**Step 3, schedule.** `.github/workflows/brightsky-verify.yml` exists (3722 bytes), and its test `stepper/tests/unit/test_brightsky_workflow_file.py` is one of the 2177 that passed. It cannot fire until it reaches `main` and the secrets are set.

**Step 2, manual check: run 1 exits 1, because the browser cannot reach openlibrary.org.** Environment: the local bright-sky backend on `claude/workflow-verify` at `http://127.0.0.1:3001` (PostgreSQL, Redis), `BRIGHTSKY_API_URL` and `BRIGHTSKY_BRIDGE_TOKEN` from the caller's env script, `BROWSER_EXECUTABLE_PATH=/opt/pw-browsers/chromium`. Before the run, `data.currentVersion.status` was `unverified` (v1).

Run 1, `python3 -m stepper brightsky verify openlibrary-find-author`, exit 1. Ticket 15's envelope fix works: the queue and detail reads are 200, the 4 steps map, and the report posts:
```
brightsky request method=GET path=/api/workflows/verification-queue status=200 attempt=1
brightsky request method=GET path=/api/workflows/openlibrary-find-author status=200 attempt=1
stepper.main | Planned 4 steps
Step 1 raised: Page.goto: net::ERR_TUNNEL_CONNECTION_FAILED at https://openlibrary.org/
[StepRunner] heal attempt 1 failed: [AIService] all providers failed for task_type='heal'. Chain tried: ['groq', 'gemini', 'claude']
[StepRunner] heal attempt 2 failed: ... task_type='heal' ...
[StepRunner] heal attempt 3 failed: ... task_type='heal_big'. Chain tried: ['claude_big']
brightsky request method=POST path=/api/workflows/openlibrary-find-author/runs status=201 attempt=1
brightsky run reported slug=openlibrary-find-author version=1 key=stepper-2c39906546cb4af0b05283093e59dc71 result=failed
openlibrary-find-author v1 failed: step 1: Page.goto: net::ERR_TUNNEL_CONNECTION_FAILED at https://openlibrary.org/
```
The token does not appear in the output (grep count 0). After the run, the check command printed `status:unverified`.

Cause: this host's egress proxy denies the host. `curl https://openlibrary.org/` → `CONNECT tunnel failed, response 403`, and the proxy's README says a 403 is a policy denial to report, not to route around. No AI key is set either, so only `embed_direct` can heal. That is not what failed here: the page never loaded.

Runs needed for exit 0: not reached (1 run, failed on network). The status check (`data.currentVersion.status`) reads `unverified`.

The heal loop ran on a `navigate` step (`calling AI for 'navigate'`). The heal (ticket 13's `_ElementOnlyHealer`) would reject a navigate swap anyway, but a network failure on navigate still goes through the 3 heal attempts. That is not a bar failure, and I changed nothing for it.

**Shortcuts taken**: none.

**For later tickets**
- This ticket needs a host where Chromium can reach `https://openlibrary.org` (the proxy allowlist, or a machine without the policy proxy). Nothing in the code needs to change for it. If the first run there heals instead of passing, it also needs an `ANTHROPIC_API_KEY`/`GROQ_API_KEY`/`GEMINI_API_KEY`, because only `embed_direct` heals without a key.
- Run 1 posted one `failed` run report for v1 to the local backend (key `stepper-2c39906546cb4af0b05283093e59dc71`). A failed report does not promote or demote, so a rerun starts from the same state.

## Attempt note

Attempt 1 (auto): the unit bar passed. The manual run failed on bright-sky's response envelope, which ticket 15 has since fixed.

Attempt 2 (auto): the unit bar passes (2177) and step 3 is confirmed. The manual run now gets through the backend calls but exits 1: `Page.goto: net::ERR_TUNNEL_CONNECTION_FAILED at https://openlibrary.org/`. The host's egress proxy answers 403 (policy denial) to `CONNECT openlibrary.org:443`. The bar needs network access to openlibrary.org (allowlisting it, or a different host), plus probably an AI key in case the first run heals. A human has to provide that. No code change would fix it, so the ticket stays open.
