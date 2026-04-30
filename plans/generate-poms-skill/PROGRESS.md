# Generate POMs Skill — Progress

## Status: COMPLETE

## Conversation Breakdown

| Conv | Phases | Scope | Status | Verify |
|------|--------|-------|--------|--------|
| 1 | 1–3 | SKILL.md frontmatter + Site Scaffold + POM Generation sections | DONE | `grep -q "POM Generation" .claude/skills/generate-poms/SKILL.md` |
| 2 | 4–5 | Glue Generation + Workflow Generation sections | DONE | `grep -q "Workflow Generation" .claude/skills/generate-poms/SKILL.md` |
| 3 | 6 | Hook Self-Correction + Error Handling sections | DONE | `grep -q "Hook Self-Correction" .claude/skills/generate-poms/SKILL.md` |
| 4 | 7 | Fixture trace + end-to-end smoke test on a temp `gen_sd` site | DONE | `claude -p "/verify-layers"` reports zero violations on generated `gen_sd` site |

See **CONVERSATION_PROMPTS.md** for exact prompts to paste in each conversation.

## Phase Detail

| # | Phase | Layer | Description | Conv | Status | Key Files |
|---|-------|-------|-------------|------|--------|-----------|
| 1 | Skill scaffold + frontmatter | Skill | Create `.claude/skills/generate-poms/SKILL.md` with name/description/argument-hint | 1 | DONE | `.claude/skills/generate-poms/SKILL.md` |
| 2 | Site scaffold section | Skill body | Append "Site Scaffold": parse args, refuse overwrite, generate `poms/<site>/__init__.py`, `config.py`, `config/config.yaml`, `pages/base_page.py`, `stepper/sites/<site>/` skeleton | 1 | DONE | `.claude/skills/generate-poms/SKILL.md` |
| 3 | POM generation section | Skill body | Append "POM Generation": cfg list rules, method derivation, hook self-correction loop | 1 | DONE | `.claude/skills/generate-poms/SKILL.md` |
| 4 | Glue generation section | Skill body | Append "Glue Generation": PageModule + nested GlueAction, register(), resolver injection rule | 2 | DONE | `.claude/skills/generate-poms/SKILL.md` |
| 5 | Workflow generation section | Skill body | Append "Workflow Generation": JSON schema, one step per glue action, no selectors in JSON | 2 | DONE | `.claude/skills/generate-poms/SKILL.md` |
| 6 | Hook awareness + error handling | Skill body | Append "Hook Self-Correction" + "Error Handling" sections | 3 | DONE | `.claude/skills/generate-poms/SKILL.md` |
| 7 | E2E smoke test | Verification | Hand-craft fixture trace, run skill, verify generated `gen_sd` site passes verify-layers and imports | 4 | DONE | `plans/generate-poms-skill/fixtures/saucedemo_trace.json` (committed); `poms/gen_sd/`, `stepper/sites/gen_sd/` (test artefacts, not committed) |

## Prerequisites
- Claude Code CLI authenticated
- Hooks wired in `.claude/settings.json` (post-edit-pom-check, layer-boundary-reminder, pyright)
- `pyright` installed
- `/verify-layers` skill exists ✓

## Blocked By
- Nothing (uses hand-crafted fixture trace; does not depend on `discover-site-skill` or `crawl-cli` being complete)
