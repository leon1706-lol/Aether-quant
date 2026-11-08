#!/usr/bin/env bash
# main.py's option paths on Lean's sample chain, one scenario per run (scripts/lean_smoke/main_option_scenarios.py). Runs on the DinD
# Codespace, in a project holding the whole repo:  bash scripts/lean_smoke/run_main_option_scenarios.sh <scale|all43|arb|assign>
# Writes /tmp/aq_lean/smoke_main_option_<scenario>.log and backtests/smoke_main_option_<scenario>/.
set -u
export PATH="$(python3 -m site --user-base)/bin:${PATH}"
SCENARIO="${1:?scenario: scale | all43 | arb | assign}"
IMAGE="aether-quant-lean:17900"
STATE_DIR="/tmp/aq_lean"
DIR="${STATE_DIR}/smoke/main_option_${SCENARIO}"
MASTER="${STATE_DIR}/data_master/data"
sudo rm -rf "${DIR}"
mkdir -p "${DIR}"
[ -d "${MASTER}" ] || { mkdir -p "${STATE_DIR}/data_master"; cp -a data "${MASTER}"; }
rsync -a --exclude data --exclude data_pre2013 --exclude data_wide --exclude data_crypto_wide --exclude backtests --exclude .git \
  --exclude .av --exclude .venv --exclude node_modules --exclude ml/datasets --exclude ml/versions --exclude visualization ./ "${DIR}/"
cp -al "${MASTER}" "${DIR}/data"
mv "${DIR}/main.py" "${DIR}/aq_main.py"
cp scripts/lean_smoke/main_option_scenarios.py "${DIR}/main.py"
echo "${SCENARIO}" > "${DIR}/scenario.txt"
python3 scripts/lean_smoke/make_option_main_config.py --out "${DIR}/config.json" --scenario "${SCENARIO}"
(cd "${DIR}" && lean backtest . --image "${IMAGE}" --no-update) > "${STATE_DIR}/smoke_main_option_${SCENARIO}.log" 2>&1
code=$?
produced="$(ls -1d "${DIR}"/backtests/*/ 2>/dev/null | sort | tail -n 1)"
if [ -n "${produced}" ]; then
  rm -rf "backtests/smoke_main_option_${SCENARIO}"
  sudo chown -R "$(id -u)" "${produced}" 2>/dev/null
  mv "${produced%/}" "backtests/smoke_main_option_${SCENARIO}"
fi
echo "SMOKE_DONE main_option_${SCENARIO} exit ${code}"
sudo rm -rf "${DIR}"
