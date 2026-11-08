#!/usr/bin/env bash
# Live-mode plumbing without a broker (V6.6.4, B6; Problems #228, #319, #323). Runs main.py itself in Lean's `live-paper` environment (PaperBrokerage) from the engine
# image with `docker run`, a FakeDataQueue for ticks, and the native Redis and Postgres of scripts/field_services.sh. Needs no QuantConnect login, no broker account,
# no key and no money; the configs live in a temp directory and lean.json and config.json are never touched. It proves plumbing, never edge.
#
# Run 1 starts the algorithm, stops Redis, then Postgres, brings both back and checks the engine is still running. Run 2 starts it again on the same project directory.
#
#   bash scripts/lean_smoke/live_plumbing.sh [seconds per run]      from the repo root on the DinD Codespace; writes /tmp/aq_lean/live_plumbing/ and the JSON report
set -u
export PATH="$(python3 -m site --user-base)/bin:${PATH}"
RUN_SECONDS="${1:-180}"
IMAGE="aether-quant-lean:17900"
STATE_DIR="/tmp/aq_lean"
DIR="${STATE_DIR}/live_plumbing"
MASTER="${STATE_DIR}/data_master/data"
export AETHER_REDIS_URL="redis://localhost:6380/0"
export AETHER_POSTGRES_DSN="postgresql://aether:aether_dev_password@localhost:5433/aether_quant"
sudo rm -rf "${DIR}"
mkdir -p "${DIR}"
[ -d "${MASTER}" ] || { mkdir -p "${STATE_DIR}/data_master"; cp -a data "${MASTER}"; }
rsync -a --exclude data --exclude data_pre2013 --exclude data_wide --exclude data_crypto_wide --exclude backtests --exclude .git \
  --exclude .av --exclude .venv --exclude node_modules --exclude ml/datasets --exclude ml/versions --exclude visualization ./ "${DIR}/project/"
cp -al "${MASTER}" "${DIR}/project/data"
python3 scripts/lean_smoke/make_live_plumbing_config.py --lean-json lean.json --out "${DIR}/launcher.json" --project-config "${DIR}/project/config.json"
bash scripts/field_services.sh up all > "${DIR}/services.log" 2>&1
# the audit worker drains main.py's audit events into Postgres, as docker-compose.yml's audit-worker does
nohup python3 -m audit.postgres_worker > "${DIR}/audit_worker.log" 2>&1 &
WORKER=$!

engine() {  # $1 = run number; blocks for RUN_SECONDS (or less if the engine exits)
  mkdir -p "${DIR}/results$1"
  docker rm -f aq_live_plumbing > /dev/null 2>&1
  docker run -d --name aq_live_plumbing --network host \
    -e AETHER_REDIS_URL="${AETHER_REDIS_URL}" -e AETHER_POSTGRES_DSN="${AETHER_POSTGRES_DSN}" \
    -v "${DIR}/project:/LeanCLI" -v "${DIR}/project/data:/Lean/Data" -v "${DIR}/results$1:/Results" \
    -v "${DIR}/launcher.json:/Lean/Launcher/bin/Debug/config.json" -w /Lean/Launcher/bin/Debug "${IMAGE}" > /dev/null
}

# run 1: wait for the warm-up, then stop Redis, then Postgres, then bring both back
engine 1
for _ in $(seq 1 90); do
  docker logs aq_live_plumbing 2>&1 | grep -q "TICKS PER SECOND:: [1-9]" && break
  sleep 2
done
sleep 20
OUTAGE_START=$(date +%s)
bash scripts/field_services.sh stop redis > "${DIR}/outage.log" 2>&1
sleep 25
bash scripts/field_services.sh stop postgres >> "${DIR}/outage.log" 2>&1
sleep 25
bash scripts/field_services.sh start all >> "${DIR}/outage.log" 2>&1
OUTAGE_SECONDS=$(( $(date +%s) - OUTAGE_START ))
sleep 30
ALIVE=false
[ "$(docker inspect -f '{{.State.Running}}' aq_live_plumbing 2>/dev/null)" = "true" ] && ALIVE=true
docker logs aq_live_plumbing > "${DIR}/engine1.log" 2>&1
docker stop -t 30 aq_live_plumbing > /dev/null 2>&1
docker logs aq_live_plumbing > "${DIR}/engine1.log" 2>&1
docker rm -f aq_live_plumbing > /dev/null 2>&1

# run 2: the same project directory again
engine 2
sleep "${RUN_SECONDS}"
docker logs aq_live_plumbing > "${DIR}/engine2.log" 2>&1
docker stop -t 30 aq_live_plumbing > /dev/null 2>&1
docker rm -f aq_live_plumbing > /dev/null 2>&1
STATE_FILE=false
sudo test -s "${DIR}/project/visualization/state.json" && STATE_FILE=true

sleep 5
kill "${WORKER}" 2>/dev/null
VERIFY_TEXT="$(python3 aq_cli.py audit-log --verify 2>&1 | tail -n 1)"
VERIFY_OK=false
echo "${VERIFY_TEXT}" | grep -q "intact\|trivially valid" && VERIFY_OK=true
python3 - "${DIR}/facts.json" "${ALIVE}" "${OUTAGE_SECONDS}" "${STATE_FILE}" "${VERIFY_OK}" "${VERIFY_TEXT}" <<'PY'
import json, sys
out, alive, seconds, state, ok, text = sys.argv[1:7]
json.dump({"alive_after_outages": alive == "true", "outage_seconds": int(seconds), "state_file_after_restart": state == "true", "audit_verify_ok": ok == "true", "audit_verify_text": text}, open(out, "w"))
PY
bash scripts/field_services.sh down >> "${DIR}/services.log" 2>&1
python3 scripts/lean_smoke/live_plumbing_report.py --dir "${DIR}" --out ml/evaluation/v664/live_plumbing.json
echo "LIVE_PLUMBING_DONE"
