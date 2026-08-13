#!/bin/bash
# Supervise one gate-pilot arm to completion, surviving harness kills.
#
# First pass runs the arm script; every later pass runs gatepilot_resume.py,
# which rebuilds per-seed state from the arm's run log so no paid round is
# redone. Detach with:
#
#   nohup setsid experiments/seedcraft/gatepilot_supervise.sh p6 \
#     >> experiments/seedcraft/out/gatepilot_p6_supervisor.log 2>&1 &
#
# Usage: gatepilot_supervise.sh <arm: p6|p7> [max_attempts]
set -u
ARM="$1"
MAX="${2:-12}"
cd "$(dirname "$0")/../.." || exit 1
PY=.venv/bin/python
LOG="experiments/seedcraft/out/gatepilot_${ARM}_pipeline.log"

for attempt in $(seq 1 "$MAX"); do
  # An existing run log means a prior pass already paid for rounds: resume it.
  if compgen -G "output/gatepilot_${ARM}_*_run_log.jsonl" > /dev/null; then
    CMD="experiments/seedcraft/gatepilot_resume.py $ARM"
  else
    CMD="experiments/seedcraft/gatepilot_${ARM}.py"
  fi
  echo "=== [$(date -u +%FT%TZ)] $ARM attempt $attempt/$MAX: $CMD ===" | tee -a "$LOG"
  $PY $CMD >> "$LOG" 2>&1
  rc=$?
  echo "=== [$(date -u +%FT%TZ)] $ARM attempt $attempt exited rc=$rc ===" | tee -a "$LOG"
  [ $rc -eq 0 ] && { echo "$ARM COMPLETE"; exit 0; }
  # Back off: a hard stop (OpenRouter key limit) fails instantly, and retrying
  # it 12 times in a row buys nothing but noise in the log.
  sleep $(( attempt * 60 ))
done
echo "$ARM GAVE UP after $MAX attempts"
exit 1
