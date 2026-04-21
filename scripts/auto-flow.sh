#!/bin/bash
# auto-flow.sh — Automated plan execution via Claude Code CLI
#
# Loops through conversations of a plan folder, each in a fresh
# Claude Code session (clean context). Stops when all conversations
# are DONE or on failure.
#
# Usage:
#   bash scripts/auto-flow.sh refactor-main
#   bash scripts/auto-flow.sh my-new-feature
#
# Prerequisites:
#   - Claude Code CLI installed and authenticated (`claude` command available)
#   - Working directory is the repo root (playwright-stepper-framework/)
#   - Git working directory is clean (no uncommitted changes)

set -euo pipefail

PLAN="${1:?Usage: bash scripts/auto-flow.sh <plan-folder-name>}"
PROGRESS_FILE="plans/$PLAN/PROGRESS.md"
MAX_RETRIES=2
CONV_COUNT=0

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Log file
mkdir -p logs
LOG_FILE="logs/auto-flow-${PLAN}-$(date +%Y%m%d_%H%M%S).log"

log() {
  local msg="[$(date +%H:%M:%S)] $*"
  echo -e "$msg" | tee -a "$LOG_FILE"
}

echo -e "${GREEN}=================================================${NC}" | tee "$LOG_FILE"
echo -e "${GREEN}  Auto-Flow: $PLAN${NC}" | tee -a "$LOG_FILE"
echo -e "${GREEN}  Log: $LOG_FILE${NC}" | tee -a "$LOG_FILE"
echo -e "${GREEN}=================================================${NC}" | tee -a "$LOG_FILE"

# Verify plan folder exists
if [ ! -f "$PROGRESS_FILE" ]; then
  echo -e "${RED}Error: $PROGRESS_FILE not found${NC}"
  echo "Available plans:"
  ls -d plans/*/ 2>/dev/null | sed 's|plans/||;s|/||'
  exit 1
fi

# Verify git is clean
if [ -n "$(git status --porcelain)" ]; then
  echo -e "${RED}Error: Working directory is not clean. Commit or stash changes first.${NC}"
  git status --short
  exit 1
fi

# Verify claude CLI is available
if ! command -v claude &> /dev/null; then
  echo -e "${RED}Error: 'claude' CLI not found. Install Claude Code first.${NC}"
  exit 1
fi

# Check if plan is already complete
check_complete() {
  if grep -qi "Status: COMPLETE" "$PROGRESS_FILE" 2>/dev/null; then
    return 0  # complete
  fi
  return 1  # not complete
}

# Count remaining TODO conversations (only from the Conversation Breakdown table)
# Extracts lines between "## Conversation Breakdown" and the next "##" heading,
# then counts rows with "| TODO |" — avoids double-counting Phase Detail rows.
count_remaining() {
  sed -n '/## Conversation Breakdown/,/^## /p' "$PROGRESS_FILE" 2>/dev/null \
    | grep -c "| TODO |" 2>/dev/null || echo "0"
}

# Main loop
while true; do
  # Check if already complete
  if check_complete; then
    echo ""
    log "${GREEN}=================================================${NC}"
    log "${GREEN}  DONE Plan $PLAN is COMPLETE!${NC}"
    log "${GREEN}  Conversations executed: $CONV_COUNT${NC}"
    log "${GREEN}  Full log: $LOG_FILE${NC}"
    log "${GREEN}=================================================${NC}"
    exit 0
  fi

  REMAINING=$(count_remaining)
  CONV_COUNT=$((CONV_COUNT + 1))

  echo ""
  log "${YELLOW}-------------------------------------------------${NC}"
  log "${YELLOW}  Starting conversation $CONV_COUNT ($REMAINING convs remaining)${NC}"
  log "${YELLOW}-------------------------------------------------${NC}"

  RETRY=0
  SUCCESS=false

  while [ $RETRY -lt $MAX_RETRIES ]; do
    OUTPUT_FILE=$(mktemp)
    EXIT_CODE=0
    log "${CYAN}  Claude Code running /next-phase $PLAN ...${NC}"
    echo "" | tee -a "$LOG_FILE"
    claude -p "/next-phase $PLAN auto" --allowedTools "Edit,Write,Read,Glob,Grep,Bash,Skill,TodoWrite,WebSearch,WebFetch" 2>&1 | tee -a "$LOG_FILE" | tee "$OUTPUT_FILE" || EXIT_CODE=$?
    echo "" | tee -a "$LOG_FILE"

    # Check for failure: non-zero exit OR "Execution error" in output
    if [ $EXIT_CODE -ne 0 ] || grep -qi "Execution error" "$OUTPUT_FILE" 2>/dev/null; then
      rm -f "$OUTPUT_FILE"
      RETRY=$((RETRY + 1))
      log "${YELLOW}  Attempt $RETRY failed (exit=$EXIT_CODE). Retrying...${NC}"

      # Check if progress was made despite the error
      if check_complete; then
        SUCCESS=true
        break
      fi

      REMAINING_NOW=$(count_remaining)
      if [ "$REMAINING_NOW" -lt "$REMAINING" ]; then
        log "${YELLOW}  Progress detected despite error. Continuing...${NC}"
        SUCCESS=true
        break
      fi
    else
      rm -f "$OUTPUT_FILE"
      SUCCESS=true
      break
    fi
  done

  if [ "$SUCCESS" = false ]; then
    log "${RED}=================================================${NC}"
    log "${RED}  FAIL after $MAX_RETRIES attempts${NC}"
    log "${RED}  Plan: $PLAN${NC}"
    log "${RED}  Completed conversations: $((CONV_COUNT - 1))${NC}"
    log "${RED}  Log saved to: $LOG_FILE${NC}"
    log "${RED}=================================================${NC}"
    exit 1
  fi

  log "${GREEN}  OK Conversation $CONV_COUNT completed${NC}"
  sleep 2
done
