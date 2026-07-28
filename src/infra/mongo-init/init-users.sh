#!/bin/bash
# Creates the cluster's users. Runs inside the mongos network namespace so the
# localhost exception lets us create the very first user; after that runs,
# every connection - including this script's later steps - needs credentials.
#
# Two accounts, deliberately:
#   root  - cluster administration, used only by the init containers
#   app   - what the backend uses: readWrite on the codeguard database only
set -euo pipefail

ROOT_USER="${MONGO_ROOT_USERNAME:?MONGO_ROOT_USERNAME is required}"
ROOT_PASS="${MONGO_ROOT_PASSWORD:?MONGO_ROOT_PASSWORD is required}"
APP_USER="${MONGO_APP_USERNAME:?MONGO_APP_USERNAME is required}"
APP_PASS="${MONGO_APP_PASSWORD:?MONGO_APP_PASSWORD is required}"
DB_NAME="${MONGO_DB:-codeguard}"
ATTEMPTS="${ATTEMPTS:-90}"

log() { echo "[init-users] $*"; }

log "waiting for mongos on 127.0.0.1:27017"
for _ in $(seq 1 "$ATTEMPTS"); do
  mongosh --quiet --host 127.0.0.1 --eval 'db.adminCommand({ping:1})' >/dev/null 2>&1 && break
  sleep 2
done

# Idempotent: on a re-run the localhost exception is already closed, so we
# authenticate instead. Either path ends with both users present.
if mongosh --quiet --host 127.0.0.1 -u "$ROOT_USER" -p "$ROOT_PASS" \
     --authenticationDatabase admin --eval 'db.adminCommand({ping:1})' >/dev/null 2>&1; then
  log "root user already exists, authenticating"
  AUTH=(-u "$ROOT_USER" -p "$ROOT_PASS" --authenticationDatabase admin)
else
  log "creating root user via the localhost exception"
  mongosh --quiet --host 127.0.0.1 admin --eval '
    db.createUser({
      user: "'"$ROOT_USER"'",
      pwd: "'"$ROOT_PASS"'",
      roles: [{ role: "root", db: "admin" }]
    });
    print("root user created");'
  AUTH=(-u "$ROOT_USER" -p "$ROOT_PASS" --authenticationDatabase admin)
fi

log "ensuring application user (readWrite on $DB_NAME only)"
mongosh --quiet --host 127.0.0.1 "${AUTH[@]}" admin --eval '
  const appUser = "'"$APP_USER"'";
  const dbName  = "'"$DB_NAME"'";
  const target  = db.getSiblingDB(dbName);
  const existing = target.getUser(appUser);
  if (existing) {
    target.updateUser(appUser, {
      pwd: "'"$APP_PASS"'",
      roles: [{ role: "readWrite", db: dbName }]
    });
    print("application user updated");
  } else {
    target.createUser({
      user: appUser,
      pwd: "'"$APP_PASS"'",
      roles: [{ role: "readWrite", db: dbName }]
    });
    print("application user created");
  }'

log "authentication is configured"
