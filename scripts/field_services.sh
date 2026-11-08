#!/usr/bin/env bash
# Real Redis and Postgres as plain processes, for scripts/field_test_services.py on a host where Docker's postgres and redis images will not start (V6.6.4: on the DinD Codespace their entrypoints
# fail with "permission denied", the same default-ACL fault that breaks non-root containers there). No Docker, no network service beyond localhost; data lives under /tmp and is thrown away.
#
#   bash scripts/field_services.sh install            # apt: postgresql and redis-server (sudo)
#   bash scripts/field_services.sh up   [redis|postgres|all]
#   bash scripts/field_services.sh stop [redis|postgres|all]
#   bash scripts/field_services.sh start [redis|postgres|all]     # same as up, and idempotent
#   bash scripts/field_services.sh down                           # stop both and delete the data
#
# Redis listens on 6380 and Postgres on 5433 (the compose file's ports); the database is `aether_quant`, the user `aether`, the password the repo's published development one.
set -u
PGDATA=/tmp/aq_pgdata
PGPORT=5433
REDISPORT=6380
PGBIN="$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -n 1)"
export PGPASSWORD="${POSTGRES_PASSWORD:-aether_dev_password}"
USER_NAME="${POSTGRES_USER:-aether}"
DB_NAME="${POSTGRES_DB:-aether_quant}"

redis_up() {
  redis-cli -p "${REDISPORT}" ping > /dev/null 2>&1 && return 0
  redis-server --port "${REDISPORT}" --save "" --appendonly no --daemonize yes --dir /tmp --logfile /tmp/aq_redis.log > /dev/null
  for _ in $(seq 1 30); do redis-cli -p "${REDISPORT}" ping > /dev/null 2>&1 && return 0; sleep 1; done
  return 1
}

redis_stop() { redis-cli -p "${REDISPORT}" shutdown nosave > /dev/null 2>&1; sleep 1; ! redis-cli -p "${REDISPORT}" ping > /dev/null 2>&1; }

postgres_up() {
  [ -n "${PGBIN}" ] || { echo "no postgres binaries: run '$0 install'" >&2; return 1; }
  if [ ! -d "${PGDATA}" ]; then
    echo "${PGPASSWORD}" > /tmp/aq_pgpw
    "${PGBIN}/initdb" -D "${PGDATA}" -U "${USER_NAME}" --auth=md5 --pwfile=/tmp/aq_pgpw > /tmp/aq_initdb.log 2>&1 || return 1
    rm -f /tmp/aq_pgpw
  fi
  "${PGBIN}/pg_isready" -h localhost -p "${PGPORT}" > /dev/null 2>&1 || "${PGBIN}/pg_ctl" -D "${PGDATA}" -o "-p ${PGPORT} -k /tmp -c listen_addresses=localhost" -l /tmp/aq_pg.log -w start > /dev/null 2>&1
  for _ in $(seq 1 30); do "${PGBIN}/pg_isready" -h localhost -p "${PGPORT}" > /dev/null 2>&1 && break; sleep 1; done
  "${PGBIN}/pg_isready" -h localhost -p "${PGPORT}" > /dev/null 2>&1 || return 1
  "${PGBIN}/psql" -h localhost -p "${PGPORT}" -U "${USER_NAME}" -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 \
    || "${PGBIN}/createdb" -h localhost -p "${PGPORT}" -U "${USER_NAME}" "${DB_NAME}"
}

postgres_stop() { "${PGBIN}/pg_ctl" -D "${PGDATA}" -m fast -w stop > /dev/null 2>&1; ! "${PGBIN}/pg_isready" -h localhost -p "${PGPORT}" > /dev/null 2>&1; }

target="${2:-all}"
case "${1:-}" in
  install) sudo apt-get update -qq && sudo apt-get install -y -qq postgresql redis-server > /tmp/aq_apt.log 2>&1; echo "apt exit $?"; sudo service postgresql stop > /dev/null 2>&1; sudo service redis-server stop > /dev/null 2>&1; exit 0 ;;
  up | start)
    [ "${target}" = postgres ] || redis_up || exit 1
    [ "${target}" = redis ] || postgres_up || exit 1 ;;
  stop)
    [ "${target}" = postgres ] || redis_stop || exit 1
    [ "${target}" = redis ] || postgres_stop || exit 1 ;;
  down) redis_stop; postgres_stop; rm -rf "${PGDATA}" ;;
  *) echo "usage: $0 install | up|start|stop [redis|postgres|all] | down" >&2; exit 2 ;;
esac
