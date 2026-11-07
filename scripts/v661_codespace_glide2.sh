#!/usr/bin/env bash
# R-GLIDE2, then R-BLEND2's run configs, on the training Codespace. Run detached, poll /tmp/aq_v661/status.
set -u
OUT=/tmp/aq_v661
mkdir -p "${OUT}"
STATUS="${OUT}/status"
mark() { echo "$(date -u +%FT%TZ) $1" >> "${STATUS}"; }
mark GLIDE2_START
[ -f ml/generations/glide2_policy.json ] || { python3 scripts/v661_glide.py run2 --paths 2000 --workers 4 > "${OUT}/glide2.log" 2>&1; mark "GLIDE2 exit $?"; }
python3 scripts/cycle_lean.py make3 > "${OUT}/make3.log" 2>&1
mark "MAKE3 exit $?"
mark GLIDE2_DONE
