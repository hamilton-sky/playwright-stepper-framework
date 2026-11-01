# Learnings: brightsky-verify

Things a fresh worker would otherwise waste time rediscovering: a command that works, a
trap, a quirk of the environment. Append one or two lines, newest last, tagged with your
ticket number. Never edit or delete another line. Keep it short; a human prunes it.

- (02) pytest.ini's addopts uses log options, so `-p no:logging` breaks the run; run pytest with the plain commands.
- (02) `RunStep.step_number` is capped at 50, so a test that needs 51 run steps must repeat a number (length is checked before uniqueness).
- (03) The acceptance mapping file also imports `stepper.brightsky.targets` (ticket 11), so 7 of its tests fail with ModuleNotFoundError until then; the rest pass.
- (04) To unit-test a provider request, monkeypatch `anthropic.Anthropic` (it is imported inside `ClaudeProvider.chat`); see `_stub_anthropic` in test_ai_providers.py.
- (10) This host sets `no_proxy`/`NO_PROXY` and `https_proxy`; a proxy-bypass test must delenv both no_proxy spellings and set upper and lower case proxies, or it passes trivially.
