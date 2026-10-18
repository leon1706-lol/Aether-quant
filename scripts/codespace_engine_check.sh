#!/usr/bin/env bash
# Build the engine image and check its API on a DinD Codespace (V6.3.0; the dev PC's Docker Desktop could not start).
# Run detached after the Lean runs, in the same Codespace lifetime (AGENTS.md rule 13):
#   setsid nohup bash scripts/codespace_engine_check.sh > /tmp/aq_lean/engine.log 2>&1 < /dev/null &
# Writes /tmp/aq_lean/engine_status (ENGINE_OK | ENGINE_FAILED <step>) and the API answer to /tmp/aq_lean/assets_status.json.
# The engine runs alone with docker-compose.yml's mounts: on this host the alpine redis / postgres images fail to exec
# their entrypoint (permission denied), and the API degrades without them by design.
set -u
STATE=/tmp/aq_lean
NAME=aq-engine-check
mkdir -p "${STATE}"
fail() { echo "ENGINE_FAILED $1" > "${STATE}/engine_status"; docker rm -f "${NAME}" > /dev/null 2>&1; exit 1; }
: > "${STATE}/engine_status"
docker compose build engine || fail build
docker rm -f "${NAME}" > /dev/null 2>&1
docker run -d --name "${NAME}" -p 8001:8000 -e AETHER_ENV=docker \
  -v "${PWD}/ml:/app/ml" -v "${PWD}/visualization:/app/visualization" \
  -v "${PWD}/lean.json:/app/lean.json:ro" -v "${PWD}/data/reference:/app/data/reference:ro" \
  aether-quant-engine:latest || fail run
code=0
for _ in $(seq 1 60); do
  code=$(curl -s -o "${STATE}/assets_status.json" -w '%{http_code}' http://localhost:8001/api/assets-status || true)
  [ "${code}" = "200" ] && break
  sleep 5
done
[ "${code}" = "200" ] || { docker logs "${NAME}" | tail -n 40; fail "assets-status http ${code}"; }
docker image inspect aether-quant-engine:latest --format '{{.Id}}' > "${STATE}/engine_image.txt"
docker rm -f "${NAME}" > /dev/null
echo ENGINE_OK > "${STATE}/engine_status"
