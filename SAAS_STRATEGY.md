# Stepper SaaS — Revised Strategy

## Core Thesis

The moat is self-healing + local execution. No competitor does both.
Ship Phase 2 fast. Don't block on infrastructure rewrites.

---

## Revised Phase Order

```
Phase 1 — Local Agent + Cloud API  (ship this first)
Phase 2 — JSON-native engine       (derived from real usage)
Phase 3 — Visual flow builder      (no-code promise lands here)
Phase 4 — Enterprise SaaS
```

**Why swap Phases 1 and 2:**
The original Phase 1 (JSON-native engine) is infrastructure work with zero
customer-facing value. Real customer workflows will tell you which Python
glue actions are worth genericizing into JSON. Build bottom-up from observed
patterns, not top-down as a prerequisite.

---

## Phase 1 — Local Agent + Cloud API

Customers: developer-led QA teams (not no-code yet — that's Phase 3).
Pitch: *"QA automation without a framework expert. Edit JSON, not Python."*

### What to build

```
Cloud (FastAPI)
  POST /teams                  create team, get api-key
  GET  /runs/pending           agent polls this
  POST /runs/{id}/logs         agent streams log chunks
  POST /runs/{id}/result       final pass/fail + screenshot
  POST /heals                  heal suggestion from local healer
  GET  /heals/approved         agent pulls down approved patches
  GET  /runs                   dashboard: run history
  GET  /heals/pending          dashboard: heal approval queue

Local Agent (pip install stepper-agent)
  stepper-agent start --api-key sk-xxx
  Polls /runs/pending every 3s
  Executes workflow locally via existing StepRunner
  Streams logs, posts result, posts heal suggestions
  Syncs approved heals back to local elements.json
```

### Polling is fine at V1 scale

3s polling × 100 agents = 2,000 req/min. Trivial for any modern API.
Upgrade to SSE in Phase 3 when real-time log streaming is a visible feature.

### DB schema — scope team_id from day one

Every table gets `team_id` as a foreign key from the start.
Don't build team management UI yet — just enforce the isolation boundary
in the data model. One afternoon of work now prevents a full schema rewrite later.

```
teams         (id, api_key, name)
workflows     (id, team_id, name, workflow_json, elements_json)
runs          (id, team_id, workflow_id, agent_id, status, created_at)
run_logs      (id, run_id, chunk, ts)
heals         (id, team_id, element_name, before_cfg, after_cfg,
               confidence, status, approved_by, approved_at)
agents        (id, team_id, last_seen, status)
```

---

## Phase 2 — JSON-Native Engine

Now that real workflows exist, you know which Python glue is generic
and which is site-specific. Genericize only what you've seen twice.

### The escape hatch — never remove Python entirely

Add one engine action: `run_script`. Complex logic that doesn't fit JSON
stays in Python scripts alongside the workflow.

```json
{"action": "run_script", "script": "scripts/clear_reading_list.py", "params": {}}
```

```
stepper/sites/openlibrary/
  workflows/
    reading_list.json
  scripts/
    clear_reading_list.py     ← escape hatch for complex flows
  elements.json               ← replaces POM constants
  step_templates.json         ← replaces simple glue
```

This keeps the "zero-Python for simple sites" promise without pretending
JSON can replace Python for stateful, iterative flows.

### AI resolver cost — cache picks in elements.json

When the AI resolver (Phase 3 of the cascade) picks an element, write the
winning cfg back into elements.json at priority 5. Next run: deterministic
hit, no AI call. AI only fires again after a heal invalidates the cache.

```json
"login_btn": [
  {"css": ".login-btn-v2", "priority": 5, "_ai_cached": true},
  {"role": "button", "name": "Sign in", "priority": 10},
  {"text": "Login", "priority": 20},
  {"css": ".login-cta", "priority": 30}
]
```

Cost drops to near-zero after the first run per element.

---

## Phase 3 — Visual Flow Builder

This is where the no-code pitch becomes true. Target user shifts from
developer-led QA teams to pure QA engineers.

### Element Picker implementation

The picker runs in the local agent, not the cloud:

```
Builder requests screenshot  ──►  local agent opens browser, takes screenshot
                             ◄──  base64 PNG

User clicks element on screenshot
                             ──►  {x, y} sent to local agent
                                  agent inspects DOM at coords
                                  extracts role, aria-label,
                                  placeholder, text, id, css
                             ◄──  ranked cfg list

Saved to elements.json with user-chosen name
```

No cloud browser needed. Local agent handles DOM inspection.
Upgrade communication to WebSocket/SSE here for real-time log streaming.

---

## Phase 4 — Enterprise SaaS

- Multi-tenant element libraries (team inherits org library, overrides locally)
- Scheduled runs + CI/CD hook (GitHub Actions: `stepper-agent run --workflow X`)
- Role-based heal approvals (dev team auto-approves, prod requires sign-off)
- Audit trail: who approved what heal, when, what confidence score

---

## What Never Changes

The Python engine floor stays Python forever. QA users never touch it.

```
ElementResolver cascade   deterministic + semantic + AI pick
StepRunner                retry, observer, error wrapping
Self-Healer               Groq → Gemini → Claude provider chain
ActionRegistry            generic action library grows here
PlaywrightDriver          browser abstraction
```

Everything above this floor trends toward JSON. New sites, new flows,
new element libraries — all JSON, eventually all zero-Python.

---

## The Pitch (per phase)

| Phase | Customer | Pitch |
|---|---|---|
| 1 | Dev-led QA teams | "QA automation without a framework expert" |
| 2 | QA engineers who know JSON | "Zero-Python for new sites" |
| 3 | Pure QA / non-developers | "No-code. Self-healing. Your data stays local." |
| 4 | Enterprise / security-conscious | "Audit trail. Role-based approvals. SOC 2 ready." |
