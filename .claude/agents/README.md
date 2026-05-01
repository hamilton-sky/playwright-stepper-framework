# Agents

Agents are architectural roles with behavioral contracts.
A role defines HOW the agent thinks. Skills are the abilities that role can execute.

## Role Map

| Agent | Role | Model | Skills | Invoke when |
|---|---|---|---|---|
| `brainstorm` | architect | opus | storm, plan-feature | strategic thinking, design decisions, trade-offs |
| `implement` | executor | sonnet | next-phase | coding, verification, staying in scope |
| `quick` | analyst | haiku | retro | fast lookups, short summaries, focused tasks |

## Architecture

```
role: architect  (brainstorm)
  behavior: thinks in layers, surfaces trade-offs,
            one Q/turn, takes a position
  skills:   storm ──────────► explore ideas
            plan-feature ───► produce a plan

role: executor   (implement)
  behavior: stays in scope, verifies before done,
            no silent changes, reports blockers
  skills:   next-phase ─────► implement a conversation

role: analyst    (quick)
  behavior: direct, 2 tool calls max, no preamble
  skills:   retro ──────────► extract learnings
```

## Handoff contract (file-based)

```
storm (architect)
  └─► STORM_SEED.md
            │
            ▼
      plan-feature (architect)
            └─► plans/<feature>/
                      │
                      ▼
              next-phase (executor) × N
                      └─► PROGRESS.md (COMPLETE)
                                │
                                ▼
                          retro (analyst)
                                └─► RETRO.md
```

## For teams

Each role is a clear ownership boundary:
- **architect** owns: thinking before building
- **executor** owns: building what was planned
- **analyst** owns: learning and reporting fast

Invoke by role when coordinating: "this needs the architect" → use `brainstorm` agent.
