#!/usr/bin/env bash
# Run one smoke algorithm on the DinD Codespace, in its own project: bash scripts/lean_smoke/run.sh <option_structures|futures_margin>
# Needs the image and the data master of scripts/codespace_lean_parallel.sh. Writes /tmp/aq_lean/smoke_<name>.log and
# backtests/smoke_<name>/.
set -u
export PATH="$(python3 -m site --user-base)/bin:${PATH}"
NAME="${1:?smoke name}"
IMAGE="aether-quant-lean:17900"
STATE_DIR="/tmp/aq_lean"
DIR="${STATE_DIR}/smoke/${NAME}"
MASTER="${STATE_DIR}/data_master/data"
sudo rm -rf "${DIR}"
mkdir -p "${DIR}"
[ -d "${MASTER}" ] || { mkdir -p "${STATE_DIR}/data_master"; cp -a data "${MASTER}"; }
cp -al "${MASTER}" "${DIR}/data"
cp -r portfolio risk features execution "${DIR}/"
cp json_safety.py "${DIR}/" 2>/dev/null
cp "scripts/lean_smoke/${NAME}.py" "${DIR}/main.py"
cp lean.json "${DIR}/lean.json"
cat > "${DIR}/config.json" <<EOF
{"algorithm-language": "Python", "parameters": {}, "description": "V6.5.0 smoke ${NAME}", "local-id": 650}
EOF
(cd "${DIR}" && lean backtest . --image "${IMAGE}" --no-update) > "${STATE_DIR}/smoke_${NAME}.log" 2>&1
code=$?
produced="$(ls -1d "${DIR}"/backtests/*/ 2>/dev/null | sort | tail -n 1)"
if [ -n "${produced}" ]; then
  rm -rf "backtests/smoke_${NAME}"
  sudo chown -R "$(id -u)" "${produced}" 2>/dev/null
  mv "${produced%/}" "backtests/smoke_${NAME}"
fi
echo "SMOKE_DONE ${NAME} exit ${code}"
sudo rm -rf "${DIR}"
