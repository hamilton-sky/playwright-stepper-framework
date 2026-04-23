# Stepper Framework — Architecture & SaaS Evolution

## Current Architecture (Three-Layer Python Stack)

```
╔══════════════════════════════════════════════════════╗
║  Flow Layer  stepper/sites/*/workflows/*.json        ║
║  Controls order, conditions, variables, loops        ║
╠══════════════════════════════════════════════════════╣
║  Glue Layer  stepper/sites/*/pages/*.py              ║
║  Maps workflow steps → POM calls                     ║
║  Injects page= and resolver= into every POM          ║
╠══════════════════════════════════════════════════════╣
║  POM Layer   poms/*/pages/*.py                       ║
║  Selectors (cfg lists) + raw page interactions       ║
╠══════════════════════════════════════════════════════╣
║  Engine      stepper/engine/                         ║
║  ActionRegistry · StepRunner · ElementResolver       ║
║  Self-Healer · Reporters · Planner                   ║
╚══════════════════════════════════════════════════════╝
```

Dependency direction: Flow → Glue → POM → Engine. Never reversed.

---

## The Evolution: JSON-Native Stack

The insight: every Python layer above the engine can be replaced by JSON,
because the element resolver cascade already speaks semantic descriptors
(role, label, placeholder, text, id, css, xpath) — not hardcoded selectors.

```
╔══════════════════════════════════════════════════════╗
║  workflow.json   (unchanged — flow stays JSON)       ║
╠══════════════════════════════════════════════════════╣
║  step_templates.json   (replaces Glue layer)         ║
║  Named reusable step sequences — steps-in-steps      ║
╠══════════════════════════════════════════════════════╣
║  elements.json   (replaces POM constants)            ║
║  Named cfg lists: role/label/placeholder/text/css    ║
╠══════════════════════════════════════════════════════╣
║  Engine      stepper/engine/   (unchanged)           ║
║  Generic actions: fill, click, navigate, assert ...  ║
║  ElementResolver cascade · Self-Healer               ║
╚══════════════════════════════════════════════════════╝
```

### What each JSON file looks like

**elements.json** — the JSON POM

```json
{
  "login_btn": [
    {"role": "button", "name": "Sign in", "priority": 10},
    {"text": "Login",                      "priority": 20},
    {"css":  ".login-cta",                 "priority": 30}
  ],
  "username_field": [
    {"label":       "Username",  "priority": 10},
    {"placeholder": "Email",     "priority": 20},
    {"id":          "username",  "priority": 30}
  ]
}
```

**step_templates.json** — the JSON Glue (steps-in-steps)

```json
{
  "do_login": [
    {"action": "fill",  "element": "$elements.username_field", "value": "${params.username}"},
    {"action": "fill",  "element": "$elements.password_field", "value": "${params.password}"},
    {"action": "click", "element": "$elements.login_btn"}
  ]
}
```

**workflow.json** — unchanged, calls templates by name

```json
{
  "steps": [
    {"action": "navigate", "params": {"url": "${config.base_url}"}},
    {"action": "do_login",  "params": {"username": "${env.USER}", "password": "${env.PASS}"}},
    {"action": "assert_visible", "element": "$elements.dashboard_header"}
  ]
}
```

---

## Self-Healing in the JSON Stack

Self-healing becomes dramatically more powerful when element definitions live
in one place (`elements.json`) rather than scattered across Python files.

```
Element drifts on live site
          │
          ▼
    Step fails at runtime
          │
          ▼
    Healer inspects DOM
    (Groq → Gemini → Claude)
          │
          ▼
    Patches elements.json ◄── one file, one fix
          │
          ├──► workflow_A.json  ✓ healed automatically
          ├──► workflow_B.json  ✓ healed automatically
          └──► workflow_C.json  ✓ healed automatically
```

### Heal confidence model (for QA)

| Confidence | Behaviour |
|---|---|
| ≥ 0.90 | Auto-patch, log change |
| 0.70 – 0.89 | Suggest + require approval |
| < 0.70 | Flag for human review |

Auto-heal silently for low-risk flows; require approval for production test suites.

---

## Generic Engine Actions (no Python site code needed)

The engine ships a standard action library. New sites need zero Python:

| Action | Params | Notes |
|---|---|---|
| `navigate` | `url` | Supports `${context.var}` interpolation |
| `fill` | `element`, `value` | element = cfg list or `$elements.name` ref |
| `click` | `element` | same |
| `assert_visible` | `element` | |
| `assert_text` | `element`, `expected` | |
| `store` | `key`, `element` | scrapes text → context |
| `transform` | `key`, `source`, `pattern` | regex extract from scraped text |
| `switch_frame` | `frame_selector` | iframe support |
| `upload_file` | `element`, `path` | file input handling |
| `open_tab` | `url` | multi-tab orchestration |
| `switch_tab` | `index` | |
| `forEach` | `items`, `steps` | loop over context list |
| `when` | `condition`, `steps` | conditional branch |
| `call` | `template`, `params` | steps-in-steps invocation |

---

## SaaS Vision

### Target user: QA Engineer (non-developer)

```
QA pain today                    Stepper SaaS solves
─────────────────────────────    ──────────────────────────────
Need devs to write test code     No-code visual flow builder
Tests break when site updates    Self-healer patches elements.json
Hard for PM/QA to read tests     JSON workflows = readable spec
Slow to cover new sites          Zero-Python onboarding
Maintenance is a full-time job   Heal-once, fix-everywhere
Can't test internal/VPN apps     Local engine runs inside network
```

---

## Deployment Model: Hybrid SaaS (Local Engine + Cloud Dashboard)

The browser never runs in the cloud. The user's machine runs Playwright.
The cloud stores JSON, receives results, and hosts the dashboard.

```
╔════════════════════════════════════════════════════╗
║           SaaS Cloud (your server)                 ║
║                                                    ║
║  ┌──────────────────┐   ┌──────────────────────┐  ║
║  │  Workflow Studio │   │   Heal Dashboard      │  ║
║  │  drag-and-drop   │   │   approve / reject    │  ║
║  │  element picker  │   │   diff view           │  ║
║  └──────────────────┘   └──────────────────────┘  ║
║                                                    ║
║  DB: workflow.json · elements.json · run results   ║
║  API: /runs/pending · /runs/{id}/logs · /heals     ║
╚════════════════════════════════════════════════════╝
          ▲  poll every 3s          │  workflow + elements JSON
          │  POST logs/results      ▼
╔════════════════════════════════════════════════════╗
║        Local Agent  (user's machine)               ║
║                                                    ║
║   pip install stepper-agent                        ║
║   stepper-agent start --api-key sk-xxx             ║
║                                                    ║
║   Stepper Engine · Playwright · Self-Healer        ║
║   runs behind firewall · accesses internal apps    ║
╚════════════════════════════════════════════════════╝
```

### Why Hybrid beats full-cloud for QA

| | Full Cloud | Hybrid (Stepper) |
|---|---|---|
| Internal/VPN apps | Cannot reach | Works natively |
| Browser compute cost | You pay | Customer pays |
| Sensitive data exposure | Flows through cloud | Stays on machine |
| Firewall config needed | Inbound ports open | Outbound only |
| Enterprise sales objection | Data leaves network | Data stays local |

The pitch: *"We store your instructions. Your data never leaves your network."*

### The communication bridge (V1 — polling over HTTP)

WebSocket is overkill for V1. Simple polling is firewall-friendly and
works through every proxy:

```
Local Agent                        Cloud API
───────────                        ─────────
GET /runs/pending?agent_id=X  ──►  returns pending run or {}
                              ◄──  {run_id, workflow_json, elements_json}

[executes locally via Playwright]

POST /runs/{id}/logs          ──►  streams log chunks as they happen
POST /runs/{id}/result        ──►  final pass/fail + screenshots

POST /heals                   ──►  heal suggestion from local healer
GET  /heals/approved          ──►  pulls down approved patches
[updates local elements.json]
```

Upgrade path: replace polling with SSE or WebSocket in V2 for real-time
log streaming in the dashboard. V1 polling is enough to ship.

### Agent install — the sales moment

```bash
pip install stepper-agent
stepper-agent start --api-key sk-xxx
# Agent appears as "online" in the dashboard immediately.
```

No Docker. No open ports. No config files. One command.

---

## Competitive Landscape

```
Tool              Execution    Self-healing   Local/internal   No-code
────────────────  ───────────  ─────────────  ───────────────  ───────
Cypress Cloud     Cloud only   No             No               No
Playwright CI     CI only      No             Partial          No
Applitools        Cloud only   Visual only    No               No
Testim / Mabl     Cloud only   Limited        No               Yes
─────────────────────────────────────────────────────────────────────
Stepper Hybrid    Local agent  Yes (AI)       Yes              Yes
```

Self-healing is the only feature that solves the \#1 reason QA automation
fails at scale: maintenance burden. Every competitor makes you write tests.
Stepper writes and maintains them.

---

## The Heal Loop in SaaS Context

One approval in the dashboard heals every agent running that workflow:

```
Element drifts on live site
        │
        ▼
Local agent detects step failure
        │
        ▼
Self-healer inspects DOM
(Groq → Gemini → Claude)
        │
        ▼
POST heal suggestion → cloud DB
        │
        ▼
QA lead sees diff in dashboard
  Before: {role:"button", name:"Sign in"}
  After:  {role:"button", name:"Log in"}
  [Approve]  [Edit]  [Reject]
        │
        ▼  (on approve)
elements.json updated in cloud DB
        │
        ▼
Next agent poll syncs fix down
        │
        ├──► Agent A  ✓ healed
        ├──► Agent B  ✓ healed
        └──► Agent C  ✓ healed
```

### Heal confidence model

| Confidence | Behaviour |
|---|---|
| ≥ 0.90 | Auto-patch, log change, no approval needed |
| 0.70 – 0.89 | Suggest in dashboard + require approval |
| < 0.70 | Flag for human review, block auto-patch |

Configure per-team: development teams auto-approve, production suites always require sign-off.

---

### Platform Architecture (full picture)

```
╔═══════════════════════════════════════════════════════╗
║              Visual Flow Builder (Web UI)             ║
║                                                       ║
║  Step palette     Condition builder   Element picker  ║
║  [Navigate]       when: ctx.count>5   Click element   ║
║  [Fill]      ──►  forEach: ctx.books  on screenshot   ║
║  [Click]          call: do_login      → auto-cfg list ║
║                                                       ║
║  generates ──► workflow.json + elements.json          ║
╠═══════════════════════════════════════════════════════╣
║              Cloud API (FastAPI)                      ║
║                                                       ║
║  Run queue · Results store · Heal approval store      ║
║  Agent registry (online/offline status)               ║
╠═══════════════════════════════════════════════════════╣
║              Heal Dashboard                           ║
║                                                       ║
║  "login_btn drifted on saucedemo.com"                 ║
║  Before: {role: "button", name: "Sign in"}            ║
║  After:  {role: "button", name: "Log in"}             ║
║  [Approve]  [Edit]  [Reject]                          ║
╠═══════════════════════════════════════════════════════╣
║              Local Agent (pip install)                ║
║                                                       ║
║  StepRunner · ActionRegistry · ElementResolver        ║
║  Self-Healer · Reporters · Multi-tab · Playwright     ║
╚═══════════════════════════════════════════════════════╝
```

### Element Picker — zero-code cfg generation

```
User navigates to site in builder
          │
          ▼
Builder takes live screenshot
          │
          ▼
User clicks element on screenshot
          │
          ▼
System inspects DOM at click coords
  → extracts: role, aria-label,
    placeholder, visible text, id, css
          │
          ▼
Auto-generates ranked cfg list
  [{"role":"button","name":"Sign in","priority":10},
   {"text":"Sign in","priority":20},
   {"css":".login-btn","priority":30}]
          │
          ▼
Saved to elements.json with user-chosen name
```

### What stays Python (the engine floor)

Python is the execution substrate — it never disappears, but QA users never
touch it:

- `ElementResolver` cascade (deterministic + semantic + AI pick)
- `StepRunner` with retry, observer notification, error wrapping
- `Self-Healer` with provider chain (Groq → Gemini → Claude)
- `ActionRegistry` — new generic actions added here as the platform grows
- Browser driver abstraction (`PlaywrightDriver` / `IBrowserDriver`)

Everything above this floor is JSON. New sites, new flows, new element
libraries — all JSON, all zero-Python.

---

## Evolution Roadmap

```
Phase 1 — JSON-native engine
  Generic fill/click/assert actions accept cfg lists directly
  elements.json per site replaces POM constants
  step_templates.json replaces glue files

Phase 2 — Local Agent + Cloud API (Hybrid SaaS V1)
  stepper-agent CLI (pip install)
  Polling bridge: /runs/pending · /logs · /heals
  Basic web dashboard: run history + heal approvals

Phase 3 — Visual flow builder
  Drag-and-drop step palette
  Element picker from live screenshot
  Context variable wiring between steps
  Real-time log streaming (SSE/WebSocket upgrade)

Phase 4 — Enterprise SaaS
  Multi-tenant, per-team element libraries
  Scheduled runs + CI/CD integration (GitHub Actions hook)
  Role-based heal approval workflows
  Audit trail: who approved what heal, when
```
