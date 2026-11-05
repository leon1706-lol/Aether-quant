#!/usr/bin/env bash
# Run many Lean backtests at once on one DinD Codespace (V6.5.0). scripts/codespace_lean_dind.sh swaps config.json and ml/
# in place, so it can only run one at a time; here each run gets its own project copy under /tmp/aq_lean/run/<name>.
#   RUN_CONFIGS="ml/evaluation/run_configs/a.json ..." MAX_JOBS=3 bash scripts/codespace_lean_parallel.sh
# Same status file as the sequential runner: /tmp/aq_lean/status, LEAN_RUNNING|LEAN_DONE|LEAN_FAILED <name> [folder], ALL_DONE.
# A run reads a data root other than data/ when ml/evaluation/run_configs/<name>.dataroot names one (the pre-2013 root).
set -u
export PATH="$(python3 -m site --user-base)/bin:${PATH}"
IMAGE="aether-quant-lean:17900"
STATE_DIR="/tmp/aq_lean"
RUN_ROOT="${STATE_DIR}/run"
STATUS="${STATE_DIR}/status"
MAX_JOBS="${MAX_JOBS:-3}"
ALL_CONFIGS="${RUN_CONFIGS:-}"

# Docker data root, the image and the Lean CLI pin: the sequential runner's setup, with no runs to do.
RUN_CONFIGS="" bash scripts/codespace_lean_dind.sh
if grep -q "^LEAN_FAILED setup" "${STATUS}" 2>/dev/null; then
  exit 1
fi
: > "${STATUS}"
command -v rsync > /dev/null || sudo apt-get install -y rsync > "${STATE_DIR}/rsync_install.log" 2>&1
mkdir -p "${RUN_ROOT}"
cp config.json "${STATE_DIR}/config.json.orig"
REPO="$(pwd)"
LOCK="${STATE_DIR}/move.lock"

report() {
  (flock 9; echo "$1" >> "${STATUS}") 9> "${STATE_DIR}/status.lock"
}

run_one() {
  local run_config="$1" name dir data_root produced target stamp
  name="$(basename "${run_config}" .json)"
  dir="${RUN_ROOT}/${name}"
  if [ ! -f "${run_config}" ]; then
    report "LEAN_FAILED ${name} missing ${run_config}"
    return
  fi
  sudo rm -rf "${dir}" && mkdir -p "${dir}"
  # real copies: main.py writes under visualization/ and a shared inode would mix the runs' files
  rsync -a --exclude data --exclude data_pre2013 --exclude backtests --exclude .git --exclude .av --exclude .venv \
    --exclude ml/datasets --exclude ml/versions --exclude ml/expert_datasets --exclude ml/evaluation/run_artifacts \
    ./ "${dir}/" || { report "LEAN_FAILED ${name} copy"; return; }
  data_root="data"
  [ -f "ml/evaluation/run_configs/${name}.dataroot" ] && data_root="$(tr -d '\r\n' < "ml/evaluation/run_configs/${name}.dataroot")"
  # The data is read-only for a run, so hard links save 260 MB per copy. They cannot cross disks (the repo is not on /tmp's),
  # hence one master copy here.
  local master="${STATE_DIR}/data_master/${data_root}"
  (
    flock 7
    if [ ! -d "${master}" ]; then
      mkdir -p "$(dirname "${master}")" && cp -a "${data_root}" "${master}.partial" && mv "${master}.partial" "${master}"
    fi
  ) 7> "${STATE_DIR}/data_master.lock"
  cp -al "${master}" "${dir}/data" || { report "LEAN_FAILED ${name} data ${data_root}"; return; }
  cp "${run_config}" "${dir}/config.json"
  if [ -d "ml/evaluation/run_artifacts/${name}" ]; then
    cp -r "ml/evaluation/run_artifacts/${name}/." "${dir}/ml/"
  fi
  report "LEAN_RUNNING ${name}"
  if (cd "${dir}" && lean backtest . --image "${IMAGE}" --no-update) > "${STATE_DIR}/${name}.log" 2>&1; then
    produced="$(ls -1d "${dir}"/backtests/*/ 2>/dev/null | sort | tail -n 1)"
    if [ -z "${produced}" ]; then
      report "LEAN_FAILED ${name} no new backtest folder"
    else
      # two runs can finish in one second: the folder name must stay unique in the shared backtests/
      target="$(
        {
          flock 8
          stamp="$(basename "${produced%/}")"
          candidate="backtests/${stamp}"
          suffix=0
          while [ -e "${REPO}/${candidate}" ]; do
            suffix=$((suffix + 1))
            candidate="backtests/${stamp}-${suffix}"
          done
          mkdir -p "${REPO}/backtests"
          mv "${produced%/}" "${REPO}/${candidate}"
          echo "${candidate}"
        } 8> "${LOCK}"
      )"
      cp "${STATE_DIR}/${name}.log" "${REPO}/${target}/lean_cli.log"
      sha256sum "${run_config}" | cut -d' ' -f1 > "${REPO}/${target}/run_config.sha256"
      report "LEAN_DONE ${name} ${target}"
    fi
  else
    report "LEAN_FAILED ${name} lean exit (see ${name}.log)"
  fi
  # the Lean container runs as root and leaves root-owned files in the project
  sudo rm -rf "${dir}"
}

for run_config in ${ALL_CONFIGS}; do
  while [ "$(jobs -rp | wc -l)" -ge "${MAX_JOBS}" ]; do
    wait -n
  done
  run_one "${run_config}" &
  sleep 2
done
wait
echo "ALL_DONE" >> "${STATUS}"
