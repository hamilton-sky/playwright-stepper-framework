# Step statuses and exit codes

What a Stepper run reports, and what CI can rely on.

## The rule

**A step that did not do its job reports `failed`.** A missing element, a match
below the resolver's confidence gate, a click that did not land, a loop whose
items failed, an assertion with nothing to assert — all of these are `failed`.
Nothing that tried and could not is ever `passed`, `skipped` or `warned`.

## The five statuses

| Status | Means | Counted as a failure? |
|---|---|---|
| `passed` | the step did its job | no |
| `failed` | it did not — including a step that could not run as written | **yes** |
| `skipped` | deliberately not run: its `when:` was false, or there was no work (`ol_add_to_shelf` with nothing collected) | no |
| `healed` | the healer replaced a broken selector and the retry passed | no |
| `warned` | reserved; nothing produces it | — |

A **malformed** step — `scroll_to` with no element, `parallel` with no
sub-steps, `assert_text` with no `expected` — is `failed`, not `skipped`. It is a
fault in the workflow, and the exit code has to see it.

## Exit codes

| Command | Exits 1 when |
|---|---|
| `run <workflow>` | any step is `failed` |
| `run <workflow> --data rows.json` | any step in **any row** is `failed` |
| `validate` | any workflow is malformed (unknown action, bad nesting, bad JSON) |

`validate` does **not** fail for a domain that is unready on this machine (no
browser installed, no credentials) — it marks that workflow `OK ?`. `run` is where
an unready domain becomes a refusal.

## The report

`success_rate = passed / (passed + failed)`. `skipped` is outside the divisor on
purpose: a step deliberately not run is neither a success nor a failure.

## The healer

`--heal N` retries a step whose status is `failed` or `skipped`. A step that
reports `failed` for a missing element is therefore exactly what reaches the
healer; when the healed retry passes, the step is reported `healed`.

## Where this is enforced

| Test | Holds |
|---|---|
| `test_not_found_fails_the_step.py` | not-found and below-threshold elements fail; `when:` skips stay skips |
| `test_assertion_input_validation.py` | an assertion with nothing to assert fails |
| `test_for_each_item_action.py` | a loop reports its items' failures |
| `test_parallel_action.py` | `parallel` with no sub-steps fails |
| `test_failure_propagation.py` | no POM or glue action drops an interaction's result |
| `test_cli.py` | `run --data` exits on its rows' results |
