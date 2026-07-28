#!/bin/bash
# Initiates the rs0 shard replica set. Runs inside mongodb1's network namespace
# so the localhost exception applies (see init-cfg-rs.sh for why).
set -euo pipefail

MEMBERS="${SHARD_HOSTS:-mongodb1:27017 mongodb2:27017 mongodb3:27017}"
ATTEMPTS="${ATTEMPTS:-90}"

log() { echo "[init-shard-rs] $*"; }

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

# Peers are reached by hostname; sharing mongodb1's namespace keeps us on the
# same Docker network, so their DNS names still resolve.
MEMBER_JSON=$(echo "$MEMBERS" | awk '{for (i=1;i<=NF;i++) printf "{_id:%d, host:\"%s\"}%s", i-1, $i, (i<NF ? "," : "")}')

log "initiating rs0 with: $MEMBERS"
mongosh --quiet --host 127.0.0.1 --eval '
  try {
    rs.status();
    print("rs0 already initiated");
  } catch (e) {
    rs.initiate({ _id: "rs0", members: ['"$MEMBER_JSON"'] });
    print("rs0 initiated");
  }'

log "waiting for PRIMARY"
for _ in $(seq 1 "$ATTEMPTS"); do
  mongosh --quiet --host 127.0.0.1 --eval 'quit(db.hello().isWritablePrimary ? 0 : 1)' >/dev/null 2>&1 && {
    log "rs0 is PRIMARY"; exit 0; }
  sleep 2
done

log "ERROR: rs0 never became PRIMARY"
exit 1
