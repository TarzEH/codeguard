#!/bin/bash
# Initialises the config-server replica set and the shard replica set.
#
# The previous setup required a human to run these commands by hand, which is
# why the initialised /data/db files ended up committed to git. This container
# does it on every `docker compose up` and is idempotent, so the cluster can be
# rebuilt from nothing.
set -euo pipefail

CFG_HOST="${CFG_HOST:-mongo_cfgserv:27017}"
SHARD_HOSTS="${SHARD_HOSTS:-mongodb1:27017 mongodb2:27017 mongodb3:27017}"
ATTEMPTS="${ATTEMPTS:-90}"

log() { echo "[init-replicasets] $*"; }

wait_for_mongod() {
  local host=$1
  log "waiting for mongod on $host"
  for _ in $(seq 1 "$ATTEMPTS"); do
    if mongosh --quiet --host "$host" --eval 'db.adminCommand({ping:1})' >/dev/null 2>&1; then
      log "$host is accepting connections"
      return 0
    fi
    sleep 2
  done
  log "ERROR: timed out waiting for $host"
  return 1
}

wait_for_primary() {
  local host=$1
  log "waiting for $host to become PRIMARY"
  for _ in $(seq 1 "$ATTEMPTS"); do
    if mongosh --quiet --host "$host" --eval 'quit(db.hello().isWritablePrimary ? 0 : 1)' >/dev/null 2>&1; then
      log "$host is PRIMARY"
      return 0
    fi
    sleep 2
  done
  log "ERROR: $host never became PRIMARY"
  return 1
}

wait_for_mongod "$CFG_HOST"
for host in $SHARD_HOSTS; do
  wait_for_mongod "$host"
done

# --- config server replica set ---------------------------------------------
log "initiating config replica set cfgrs"
mongosh --quiet --host "$CFG_HOST" --eval '
  try {
    rs.status();
    print("cfgrs already initiated");
  } catch (e) {
    rs.initiate({
      _id: "cfgrs",
      configsvr: true,
      members: [{ _id: 0, host: "'"$CFG_HOST"'" }]
    });
    print("cfgrs initiated");
  }'

# --- shard replica set ------------------------------------------------------
PRIMARY_HOST=$(echo "$SHARD_HOSTS" | awk '{print $1}')
MEMBERS=$(echo "$SHARD_HOSTS" | awk '{for (i=1;i<=NF;i++) printf "{_id:%d, host:\"%s\"}%s", i-1, $i, (i<NF ? "," : "")}')

log "initiating shard replica set rs0"
mongosh --quiet --host "$PRIMARY_HOST" --eval '
  try {
    rs.status();
    print("rs0 already initiated");
  } catch (e) {
    rs.initiate({ _id: "rs0", members: ['"$MEMBERS"'] });
    print("rs0 initiated");
  }'

wait_for_primary "$CFG_HOST"
wait_for_primary "$PRIMARY_HOST"

log "replica sets are ready"
