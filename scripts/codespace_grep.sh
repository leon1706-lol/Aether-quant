#!/usr/bin/env bash
# bash scripts/codespace_grep.sh <log file> [extended regex] [tail lines]   (default pattern: step markers, memory, failures)
cd "$(dirname "$0")/.."
grep -nE "${2:-^=== |ABORT|IDENTICAL|differs|memory |Terminated|Traceback|Error}" "${1:?log file}" | tail -n "${3:-25}" | cut -c1-220
echo "--- last lines"; tail -n 4 "$1" | cut -c1-220
