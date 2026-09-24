# Stepper Framework — Claude Code Guide

## Directory Structure

```
playwright-stepper-framework/
│
├── poms/                             # Pure Page Object Model layer
│   ├── shared/                       # Shared across ALL sites
│   │   ├── base_page.py              # SharedBasePage — resolver helpers
│   │   ├── driver.py                 # PlaywrightDriver (IBrowserDriver impl)
│   │   ├── interfaces.py             # IBrowserDriver, IElementHandle, Delays
│   │   └── performance.py            # Performance metrics
│   ├── openLibrary/                  # OpenLibrary POMs
│   ├── saucedemo/                    # SauceDemo POMs
│   └── phpTravels/                   # phpTravels POMs
│
├── stepper/                          # The Automation Engine
│   ├── main.py                       # Entry point
│   ├── engine/                       # Core framework modules
│   │   ├── actions/                  # basic / assertions / data / flow /
│   │   │                             #   measurement, + factory; strategies.py
│   │   │                             #   re-exports them all
│   │   ├── resolvers/                # Element resolution cascade
│   │   ├── runner/                   # StepRunner, when_eval
│   │   ├── planner/                  # Claude AI planner / JSON planner
│   │   ├── reporter/                 # Reporters + test report manager
│   │   └── pages/                    # PageModule ABC + GlueAction base
│   └── sites/                        # Glue layer — wires POMs into Stepper actions
│       ├── openlibrary/pages/
│       ├── saucedemo/pages/
│       ├── phptravels/pages/     # fixtures/ serves it locally, no network
│       ├── ti/                       # the-internet — generated from a crawl;
│       │                             #   fixtures/ serves it locally, no network
│       ├── pathly/                   # Pathly Studio — Electron, attached over CDP
│       ├── db/                       # Non-browser domain — SQLite, stdlib only
│       └── */workflows/*.json        # Declarative workflow definitions
│
├── examples/
│   └── plain_pom/                    # Reference: POMs driven with no engine, no resolver
│       ├── conftest.py
│       ├── flows.py
│       └── tests/test_openlibrary_flows.py
│
├── docs/
│   ├── adding-your-app.md            # Point Stepper at your own app — six files
│   └── playwright-pitfalls.md        # Seven failure modes and their guards
├── scripts/purge-model-history.sh    # Strip the old vendored model from git history
├── ARCHITECTURE.md                   # Full architecture diagrams
└── CLAUDE.md                         # This file
```

---

## Instruction Routing

Read the relevant rule file **before** making changes in that area:

| Area | Rule file |
|---|---|
| POM layer (locators, selectors, page interactions) | [.claude/rules/pom-layer.md](.claude/rules/pom-layer.md) |
| Glue layer (action wiring, resolver injection) | [.claude/rules/glue-layer.md](.claude/rules/glue-layer.md) |
| Element resolver cascade | [.claude/rules/resolver-cascade.md](.claude/rules/resolver-cascade.md) |
| Site-specific action reference tables | [.claude/rules/site-actions.md](.claude/rules/site-actions.md) |
| Three-layer contract + dependency direction | [.claude/rules/three-layer-contract.md](.claude/rules/three-layer-contract.md) |
| Design patterns used throughout the framework | [.claude/rules/design-patterns.md](.claude/rules/design-patterns.md) |
| Adding a new site end-to-end | [docs/adding-your-app.md](docs/adding-your-app.md) |
| Generating a site from a live crawl | `/discover-site` then `/generate-poms` |
| Playwright failure modes the POMs guard against | [docs/playwright-pitfalls.md](docs/playwright-pitfalls.md) |
| Full architecture diagrams | [ARCHITECTURE.md](ARCHITECTURE.md) |

---

## Run Commands

```bash
# Unit suite — no browser, no network, no credentials. Start here.
pytest stepper/tests/unit/

# Stepper integration tests (real browser)
pytest stepper/tests/ --ignore=stepper/tests/unit

# Plain-POM example suite (real browser + OpenLibrary credentials)
cd examples/plain_pom && pytest tests/

# Discover what is available
python stepper/main.py list                  # every workflow, by site
python stepper/main.py actions --site sd     # what one site can do
python stepper/main.py --help                # all commands

# Run a workflow — by name, resolved across sites
python stepper/main.py run ol_smoke_test

# Show browser window (headless is the default)
python stepper/main.py run ol_smoke_test --show

# Check every workflow without launching a browser (exits 1 if any is invalid).
# Each line ends with the domains that workflow opens a session for. An `OK ?`
# marks a valid workflow whose domain is not ready on this machine — no browser,
# no credentials — which `run` refuses but `validate` only reports.
python stepper/main.py validate

# A browser session and a SQLite connection in one run, sharing one context.
# No network and no credentials — the page is a checked-in file:// fixture.
python stepper/main.py run db_web_mixed \
  --vars "{\"page_url\": \"file://$PWD/stepper/sites/db/fixtures/inventory.html\"}"

# The same domain with no browser at all
python stepper/main.py run db_smoke

# Watch the healer work on deliberately broken selectors. No API key needed —
# the embed-direct rung calls no provider. --no-heal-cache is what makes this a
# measurement rather than a replay of the committed heal_cache.json.
python stepper/main.py run sd_heal_test --heal 2 --no-heal-cache --show

# The eight the-internet flows, against checked-in fixtures on loopback. No
# network and no credentials — the live host is denied by this environment's
# egress policy, which is why six of the eight had never run at all.
python stepper/sites/ti/fixtures/server.py --port 8099 &
TI_BASE_URL=http://127.0.0.1:8099 python stepper/main.py run hover_over_elements_to_reveal_hidden_text

# The phpTravels booking flow, against checked-in fixtures on loopback. Its one
# workflow had never run before these existed — the host is denied here and the
# site had no CI step at all.
python stepper/sites/phptravels/fixtures/server.py --port 8098 &
PHPTRAVELS_BASE_URL=http://127.0.0.1:8098 \
PHPTRAVELS_EMAIL=user@phptravels.com PHPTRAVELS_PASSWORD=demouser \
    python stepper/main.py run hotel_booking

# Drive a running Electron app instead of launching a browser. Still the web
# domain — same actions, same POMs, same resolver cascade; only the page's
# source differs. Start Electron with --remote-debugging-port=<port> first;
# nothing here launches it. The refusal below is armed by STEPPER_ELECTRON_CDP_PORT:
# set, with nothing listening, `run` stops at plan time; unset, preflight has nothing
# to check and the run launches an ordinary browser that is not Pathly.
STEPPER_ELECTRON_CDP_PORT=9222 python stepper/main.py run <workflow>

# Run against a browser Playwright did not download for itself. Needed when the
# machine ships a prebuilt chromium of a different revision than the pinned
# playwright expects — the launch otherwise dies asking for `playwright install`.
# requirements.txt pins the matching version; this is the escape hatch.
BROWSER_EXECUTABLE_PATH=/opt/pw-browsers/chromium python stepper/main.py run ol_smoke_test
```

All three entry points land in the same `main()`:

```bash
python stepper/main.py list     # as documented throughout
python -m stepper list
stepper list                    # console script, after `pip install -e .`
```

The pre-subcommand form (`--workflow <path>`) still works and prints a one-line
note pointing at the new spelling.

---

## Adding a New Site (quick reference)

Full walkthrough with working code for all six files:
**[docs/adding-your-app.md](docs/adding-your-app.md)**.

1. `poms/<site>/pages/base_page.py` — inherit `SharedBasePage`
2. Add POM files — every interactive locator a `Locator` object (see [pom-layer rules](.claude/rules/pom-layer.md))
3. `stepper/sites/<site>/pages/` — one glue file per logical group
4. Build POMs via `self._build_pom(..., page=page, resolver=resolver, behaviour=behaviour)` (see [glue-layer rules](.claude/rules/glue-layer.md))
5. Register actions in each PageModule's `register(registry)` classmethod
6. Wire that PageModule into `stepper/sites/<site>/register.py`
