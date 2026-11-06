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

# Per-run model artifacts: main.py reads its models from fixed ml/ paths, so a run whose config needs other models ships
# them in ml/evaluation/run_artifacts/<run name>/ (same relative paths as under ml/). They are copied over ml/ for that run
# only, the originals restored (and verified) afterwards, and run_artifacts_manifest.json records what the run read.
apply_artifacts() {
  local name="$1" overlay="ml/evaluation/run_artifacts/$1" backup="${STATE_DIR}/ml_backup/$1"
  [ -d "${overlay}" ] || return 0
  rm -rf "${backup}" && mkdir -p "${backup}"
  : > "${backup}.new"
  (cd "${overlay}" && find . -type f | sed 's|^\./||' | sort) > "${backup}.list"
  while read -r rel; do
    if [ -f "ml/${rel}" ]; then
      mkdir -p "$(dirname "${backup}/${rel}")" && cp -p "ml/${rel}" "${backup}/${rel}"
    else
      echo "${rel}" >> "${backup}.new"
    fi
    mkdir -p "$(dirname "ml/${rel}")" && cp "${overlay}/${rel}" "ml/${rel}"
  done < "${backup}.list"
  python3 - "${overlay}" "${backup}.list" > "${STATE_DIR}/$1.run_artifacts_manifest.json" <<'PYEOF'
import hashlib, json, sys
overlay, listing = sys.argv[1], sys.argv[2]
rels = [line.strip() for line in open(listing) if line.strip()]
print(json.dumps({rel: hashlib.sha256(open(f"{overlay}/{rel}", "rb").read()).hexdigest() for rel in rels}, indent=1, sort_keys=True))
PYEOF
}

restore_artifacts() {
  local name="$1" overlay="ml/evaluation/run_artifacts/$1" backup="${STATE_DIR}/ml_backup/$1"
  [ -d "${overlay}" ] || return 0
  while read -r rel; do
    if grep -qxF "${rel}" "${backup}.new"; then
      rm -f "ml/${rel}"
      rmdir -p --ignore-fail-on-non-empty "$(dirname "ml/${rel}")" 2>/dev/null
    else
      cp -p "${backup}/${rel}" "ml/${rel}"
      cmp -s "${backup}/${rel}" "ml/${rel}" || return 1
    fi
  done < "${backup}.list"
}

fail_all() {
  echo "LEAN_FAILED setup $1" >> "${STATUS}"
  echo "ALL_DONE" >> "${STATUS}"
  exit 1
}

# The workspace disk is 32 GB and the Lean image ~20 GB: Docker's data root goes on the 118 GB /tmp disk.
if [ "$(docker info --format '{{.DockerRootDir}}' 2>/dev/null)" != "${DATA_ROOT}" ]; then
  sudo mkdir -p /etc/docker  # the docker-in-docker feature with Docker 29 no longer creates it (V6.4.4)
  echo "{\"data-root\": \"${DATA_ROOT}\", \"dns\": [\"168.63.129.16\"]}" | sudo tee /etc/docker/daemon.json > /dev/null
  # /tmp's default ACL gives "other" no execute: every container's / inherits it, and only root can start (Postgres can't)
  command -v setfacl > /dev/null || sudo apt-get install -y -qq acl > /dev/null 2>&1
  sudo mkdir -p "${DATA_ROOT}" && sudo setfacl -R -k "${DATA_ROOT}"
  sudo pkill dockerd
  # a new daemon refuses to start while the pid file names a live process, and on a fresh container that pid can be reused
  for _ in $(seq 1 30); do
    pgrep -x dockerd > /dev/null || break
    sleep 1
  done
  sudo rm -f /var/run/docker.pid
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
  apply_artifacts "${name}"
  echo "LEAN_RUNNING ${name}" >> "${STATUS}"
  before="$(ls -1d backtests/*/ 2>/dev/null | sort | tail -n 1)"
  if lean backtest . --image "${IMAGE}" > "${STATE_DIR}/${name}.log" 2>&1; then
    after="$(ls -1d backtests/*/ 2>/dev/null | sort | tail -n 1)"
    if [ -n "${after}" ] && [ "${after}" != "${before}" ]; then
      cp "${STATE_DIR}/${name}.log" "${after%/}/lean_cli.log"
      [ -f "${STATE_DIR}/${name}.run_artifacts_manifest.json" ] && cp "${STATE_DIR}/${name}.run_artifacts_manifest.json" "${after%/}/run_artifacts_manifest.json"
      echo "LEAN_DONE ${name} ${after%/}" >> "${STATUS}"
    else
      echo "LEAN_FAILED ${name} no new backtest folder" >> "${STATUS}"
    fi
  else
    echo "LEAN_FAILED ${name} lean exit $? (see ${name}.log)" >> "${STATUS}"
  fi
  if ! restore_artifacts "${name}"; then
    echo "LEAN_FAILED ${name} restore of ml/ after the run did not verify" >> "${STATUS}"
    break
  fi
done
[ -f "${STATE_DIR}/config.json.orig" ] && cp "${STATE_DIR}/config.json.orig" config.json
echo "ALL_DONE" >> "${STATUS}"
