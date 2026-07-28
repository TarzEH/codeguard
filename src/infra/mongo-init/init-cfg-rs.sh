#!/bin/bash
# Initiates the config-server replica set.
#
# Runs inside mongo_cfgserv's network namespace (network_mode: service:...) so
# the connection arrives on loopback. That matters: with keyfile auth enabled
# and no users yet, MongoDB's *localhost exception* is the only way in, and it
# only applies to connections originating on the node itself.
set -euo pipefail

HOST="${CFG_HOST:-mongo_cfgserv:27017}"
ATTEMPTS="${ATTEMPTS:-90}"

log() { echo "[init-cfg-rs] $*"; }

log "waiting for mongod on 127.0.0.1:27017"
for _ in $(seq 1 "$ATTEMPTS"); do
  mongosh --quiet --host 127.0.0.1 --eval 'db.adminCommand({ping:1})' >/dev/null 2>&1 && break
  sleep 2
done

# Idempotency check. `hello` is answered without authentication, and it reports
# setName once the node belongs to a configured replica set. This matters on
# re-runs: the localhost exception closes permanently once users exist, so a
# second `docker compose up` must not try to initiate again and fail.
if mongosh --quiet --host 127.0.0.1 --eval 'quit(db.hello().setName ? 0 : 1)' >/dev/null 2>&1; then
  log "replica set already configured - nothing to do"
  exit 0
fi

log "initiating cfgrs"
mongosh --quiet --host 127.0.0.1 --eval '
  try {
    rs.status();
    print("cfgrs already initiated");
  } catch (e) {
    rs.initiate({
      _id: "cfgrs",
      configsvr: true,
      members: [{ _id: 0, host: "'"$HOST"'" }]
    });
    print("cfgrs initiated");
  }'

log "waiting for PRIMARY"
for _ in $(seq 1 "$ATTEMPTS"); do
  mongosh --quiet --host 127.0.0.1 --eval 'quit(db.hello().isWritablePrimary ? 0 : 1)' >/dev/null 2>&1 && {
    log "cfgrs is PRIMARY"; exit 0; }
  sleep 2
done

log "ERROR: cfgrs never became PRIMARY"
exit 1
