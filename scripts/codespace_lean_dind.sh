#!/usr/bin/env bash
# Run Lean backtests on a temporary Docker-in-Docker Codespace (development/infrastructure.md "Lean on a DinD Codespace").
# Started detached by scripts/codespace_lean_run.ps1 -Run; every run config is copied over config.json in turn.
#   RUN_CONFIGS="ml/evaluation/run_configs/a.json ml/evaluation/run_configs/b.json" bash scripts/codespace_lean_dind.sh
# Progress: /tmp/aq_lean/status (one line per run: LEAN_RUNNING|LEAN_DONE|LEAN_FAILED <config> [backtest folder]),
# then ALL_DONE. Logs: /tmp/aq_lean/<config name>.log.
set -u
# pip installs the Lean CLI under the user base, which a detached (non-login) shell does not have on PATH
export PATH="$(python3 -m site --user-base)/bin:${PATH}"
IMAGE="aether-quant-lean:17900"
LEAN_CLI_VERSION="1.0.227"
DATA_ROOT="/tmp/docker-data"
STATE_DIR="/tmp/aq_lean"
mkdir -p "${STATE_DIR}"
STATUS="${STATE_DIR}/status"
: > "${STATUS}"

fail_all() {
  echo "LEAN_FAILED setup $1" >> "${STATUS}"
  echo "ALL_DONE" >> "${STATUS}"
  exit 1
}

# The workspace disk is 32 GB and the Lean image ~20 GB: Docker's data root goes on the 118 GB /tmp disk.
if [ "$(docker info --format '{{.DockerRootDir}}' 2>/dev/null)" != "${DATA_ROOT}" ]; then
  echo "{\"data-root\": \"${DATA_ROOT}\", \"dns\": [\"168.63.129.16\"]}" | sudo tee /etc/docker/daemon.json > /dev/null
  sudo pkill dockerd
  sleep 5
  sudo setsid nohup dockerd > "${STATE_DIR}/dockerd.log" 2>&1 < /dev/null &
  for _ in $(seq 1 60); do
    docker info > /dev/null 2>&1 && break
    sleep 2
  done
  [ "$(docker info --format '{{.DockerRootDir}}' 2>/dev/null)" = "${DATA_ROOT}" ] || fail_all "dockerd did not come up on ${DATA_ROOT}"
fi

if ! docker image inspect "${IMAGE}" > /dev/null 2>&1; then
  docker build -f Dockerfile.lean -t "${IMAGE}" . > "${STATE_DIR}/image_build.log" 2>&1 || fail_all "image build (see image_build.log)"
fi

if [ "$(pip show lean 2>/dev/null | awk '/^Version:/{print $2}')" != "${LEAN_CLI_VERSION}" ]; then
  pip install "lean==${LEAN_CLI_VERSION}" > "${STATE_DIR}/pip.log" 2>&1 || fail_all "pip install lean==${LEAN_CLI_VERSION}"
fi

[ -f config.json ] && cp config.json "${STATE_DIR}/config.json.orig"
for run_config in ${RUN_CONFIGS:-}; do
  name="$(basename "${run_config}" .json)"
  if [ ! -f "${run_config}" ]; then
    echo "LEAN_FAILED ${name} missing ${run_config}" >> "${STATUS}"
    continue
  fi
  cp "${run_config}" config.json
  echo "LEAN_RUNNING ${name}" >> "${STATUS}"
  before="$(ls -1d backtests/*/ 2>/dev/null | sort | tail -n 1)"
  if lean backtest . --image "${IMAGE}" > "${STATE_DIR}/${name}.log" 2>&1; then
    after="$(ls -1d backtests/*/ 2>/dev/null | sort | tail -n 1)"
    if [ -n "${after}" ] && [ "${after}" != "${before}" ]; then
      cp "${STATE_DIR}/${name}.log" "${after%/}/lean_cli.log"
      echo "LEAN_DONE ${name} ${after%/}" >> "${STATUS}"
    else
      echo "LEAN_FAILED ${name} no new backtest folder" >> "${STATUS}"
    fi
  else
    echo "LEAN_FAILED ${name} lean exit $? (see ${name}.log)" >> "${STATUS}"
  fi
done
[ -f "${STATE_DIR}/config.json.orig" ] && cp "${STATE_DIR}/config.json.orig" config.json
echo "ALL_DONE" >> "${STATUS}"
