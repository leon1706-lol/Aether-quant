#!/usr/bin/env bash
# V6.6.4's extra Lean and service work on the DinD Codespace, after the EOS re-pin runs have built the image and the data master (scripts/codespace_lean_run.ps1 -Run ...):
# the four option scenarios through main.py (#58-#61), the two older smokes for the record, and the real Redis + Postgres field test. Detached; poll /tmp/aq_lean/extras_status.
#   setsid nohup bash scripts/codespace_v664_extras.sh > /tmp/aq_lean/extras.log 2>&1 < /dev/null &
set -u
export PATH="$(python3 -m site --user-base)/bin:${PATH}"
STATE=/tmp/aq_lean
STATUS="${STATE}/extras_status"
mkdir -p "${STATE}" ml/evaluation/v664
cd /workspaces/Aether-quant || exit 1
mark() { echo "$(date -u +%T) $1" >> "${STATUS}"; }
mark EXTRAS_START
python3 -m pip install --quiet pyarrow httpx requests scikit-learn psycopg[binary] redis > "${STATE}/extras_pip.log" 2>&1
mark "PIP exit $?"
for scenario in scale all43 arb assign; do
  mark "SCENARIO ${scenario} start"
  bash scripts/lean_smoke/run_main_option_scenarios.sh "${scenario}" > "${STATE}/extras_${scenario}.out" 2>&1
  mark "SCENARIO ${scenario} done $(tail -n 1 "${STATE}/extras_${scenario}.out")"
  if [ -d "backtests/smoke_main_option_${scenario}" ]; then
    grep -h "SMOKE_JSON" backtests/smoke_main_option_${scenario}/log.txt "${STATE}/smoke_main_option_${scenario}.log" 2>/dev/null | sed 's/^.*SMOKE_JSON //' | sort -u > "ml/evaluation/v664/lean_smoke_option_${scenario}.jsonl"
    mark "SCENARIO ${scenario} lines $(wc -l < ml/evaluation/v664/lean_smoke_option_${scenario}.jsonl)"
  fi
done
for smoke in option_structures futures_margin; do
  mark "SMOKE ${smoke} start"
  bash scripts/lean_smoke/run.sh "${smoke}" > "${STATE}/extras_${smoke}.out" 2>&1
  mark "SMOKE ${smoke} done $(tail -n 1 "${STATE}/extras_${smoke}.out")"
done
mark "SERVICES start"
# Docker's own postgres and redis images do not start on this DinD host (their entrypoints fail with "permission denied"), so the services run as plain processes
bash scripts/field_services.sh install > "${STATE}/extras_compose.out" 2>&1
mark "SERVICES install exit $?"
bash scripts/field_services.sh up all >> "${STATE}/extras_compose.out" 2>&1
mark "SERVICES up exit $?"
export AETHER_REDIS_URL="redis://localhost:6380/0"
export AETHER_POSTGRES_DSN="postgresql://${POSTGRES_USER:-aether}:${POSTGRES_PASSWORD:-aether_dev_password}@localhost:5433/${POSTGRES_DB:-aether_quant}"
python3 scripts/field_test_services.py --report ml/evaluation/v664/field_test_services.json --stop-cmd 'bash scripts/field_services.sh stop {service}' --start-cmd 'bash scripts/field_services.sh start {service}' > "${STATE}/extras_services.out" 2>&1
mark "SERVICES exit $?"
python3 aq_cli.py audit-log --verify > "${STATE}/extras_audit_verify.out" 2>&1
mark "AUDIT_VERIFY exit $?"
python3 aq_cli.py paper-readiness > "${STATE}/extras_paper_readiness.out" 2>&1
mark "PAPER_READINESS exit $?"
bash scripts/field_services.sh down >> "${STATE}/extras_compose.out" 2>&1
mark EXTRAS_DONE
