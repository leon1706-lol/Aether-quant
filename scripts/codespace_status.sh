#!/usr/bin/env bash
# Progress of a running Codespace retrain: step markers, errors, newest artifacts, memory and disk.
#   bash scripts/codespace_status.sh [tag]      (default: the newest ml/retrain_*_a.log / _b.log)
cd "$(dirname "$0")/.."
LOG="${1:+ml/retrain_${1}_a.log}"
[ -z "${LOG}" ] && LOG="$(ls -t ml/retrain_*_[ab].log 2>/dev/null | head -1)"
echo "now $(date -u +%FT%TZ)  log ${LOG}"
grep -n '^=== \|ABORT\|Traceback\|Error' "${LOG}" | tail -8
echo "--- last lines"; tail -n 3 "${LOG}" | cut -c1-200
echo "--- newest versions"; ls -t ml/versions 2>/dev/null | head -5
echo "--- datasets"; ls -la ml/datasets 2>/dev/null | tail -6
free -m | sed -n 2p; df -h /workspaces | tail -1; pgrep -af 'train|retrain' | head -3 | cut -c1-120
