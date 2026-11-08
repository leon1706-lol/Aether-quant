#!/usr/bin/env bash
# main.py's own option order, forced once on Lean's sample chain (scripts/lean_smoke/main_option_order.py). Runs on the DinD
# Codespace, in a project holding the whole repo. Writes /tmp/aq_lean/smoke_main_option_order.log and backtests/smoke_main_option_order/.
set -u
export PATH="$(python3 -m site --user-base)/bin:${PATH}"
IMAGE="aether-quant-lean:17900"
STATE_DIR="/tmp/aq_lean"
DIR="${STATE_DIR}/smoke/main_option_order"
MASTER="${STATE_DIR}/data_master/data"
sudo rm -rf "${DIR}"
mkdir -p "${DIR}"
[ -d "${MASTER}" ] || { mkdir -p "${STATE_DIR}/data_master"; cp -a data "${MASTER}"; }
rsync -a --exclude data --exclude data_pre2013 --exclude data_wide --exclude data_crypto_wide --exclude backtests --exclude .git \
  --exclude .av --exclude .venv --exclude node_modules --exclude ml/datasets --exclude ml/versions --exclude visualization ./ "${DIR}/"
cp -al "${MASTER}" "${DIR}/data"
mv "${DIR}/main.py" "${DIR}/aq_main.py"
cp scripts/lean_smoke/main_option_order.py "${DIR}/main.py"
python3 scripts/lean_smoke/make_option_main_config.py --out "${DIR}/config.json"
(cd "${DIR}" && lean backtest . --image "${IMAGE}" --no-update) > "${STATE_DIR}/smoke_main_option_order.log" 2>&1
code=$?
produced="$(ls -1d "${DIR}"/backtests/*/ 2>/dev/null | sort | tail -n 1)"
if [ -n "${produced}" ]; then
  rm -rf backtests/smoke_main_option_order
  sudo chown -R "$(id -u)" "${produced}" 2>/dev/null
  mv "${produced%/}" backtests/smoke_main_option_order
fi
echo "SMOKE_DONE main_option_order exit ${code}"
sudo rm -rf "${DIR}"
