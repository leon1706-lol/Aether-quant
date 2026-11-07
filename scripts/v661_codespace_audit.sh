#!/usr/bin/env bash
# V6.6.1, first half of the Codespace lifetime: the model audit, read before the round's rules are written. Free cell S only. Run detached, poll /tmp/aq_v661/status.
set -u
OUT=/tmp/aq_v661
mkdir -p "${OUT}"
STATUS="${OUT}/status"
mark() { echo "$(date -u +%FT%TZ) $1" >> "${STATUS}"; }
mark AUDIT_START
python3 scripts/v661_model_audit.py > "${OUT}/audit.log" 2>&1
mark "AUDIT exit $?"
mark AUDIT_DONE
