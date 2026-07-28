#!/bin/bash
# Registers the shard with mongos and actually shards the cache collection.
#
# The old project called itself sharded but never ran enableSharding or
# shardCollection, so every document lived in a single chunk on one shard -
# that is replication, not sharding. This is the missing step.
#
# Runs after init-users.sh, so it authenticates as root rather than relying on
# the localhost exception (which is closed once the first user exists).
set -euo pipefail

MONGOS_HOST="${MONGOS_HOST:-mongos:27017}"
SHARD_SPEC="${SHARD_SPEC:-rs0/mongodb1:27017,mongodb2:27017,mongodb3:27017}"
DB_NAME="${MONGO_DB:-codeguard}"
COLLECTION="${COLLECTION:-vulnerability_cache}"
ROOT_USER="${MONGO_ROOT_USERNAME:?MONGO_ROOT_USERNAME is required}"
ROOT_PASS="${MONGO_ROOT_PASSWORD:?MONGO_ROOT_PASSWORD is required}"
ATTEMPTS="${ATTEMPTS:-90}"

log() { echo "[init-sharding] $*"; }

AUTH=(-u "$ROOT_USER" -p "$ROOT_PASS" --authenticationDatabase admin)

log "waiting for mongos on $MONGOS_HOST"
for _ in $(seq 1 "$ATTEMPTS"); do
  if mongosh --quiet --host "$MONGOS_HOST" "${AUTH[@]}" \
       --eval 'db.adminCommand({ping:1})' >/dev/null 2>&1; then
    log "mongos is accepting authenticated connections"
    break
  fi
  sleep 2
done

mongosh --quiet --host "$MONGOS_HOST" "${AUTH[@]}" --eval '
  const shardSpec = "'"$SHARD_SPEC"'";
  const dbName = "'"$DB_NAME"'";
  const collection = "'"$COLLECTION"'";
  const ns = dbName + "." + collection;

  // Every step is wrapped: re-running must be a no-op, not a failure.
  try { sh.addShard(shardSpec); print("shard added"); }
  catch (e) { print("addShard skipped: " + e.codeName); }

  try { sh.enableSharding(dbName); print("sharding enabled on " + dbName); }
  catch (e) { print("enableSharding skipped: " + e.codeName); }

  const target = db.getSiblingDB(dbName);
  try { target.createCollection(collection); print("collection created"); }
  catch (e) { print("createCollection skipped: " + e.codeName); }

  // Hashed _id spreads cache entries evenly; the _id is "PyPI:<pkg>:<version>",
  // which would otherwise cluster alphabetically into hot chunks.
  try { sh.shardCollection(ns, { _id: "hashed" }); print("collection sharded"); }
  catch (e) { print("shardCollection skipped: " + e.codeName); }

  target[collection].createIndex({ package: 1, version: 1 });

  // Single index on updated_at, carrying the TTL option. MongoDB refuses a
  // second index over the same key pattern (IndexOptionsConflict), so creating
  // a plain {updated_at:1} first would make this one silently fail. This one
  // index serves both jobs: the leader queries it to find stale entries, and
  // MongoDB expires documents from it so the cache cannot grow without bound.
  // 30 days is far longer than the 6h refresh TTL on purpose - entries between
  // the two ages are still useful as a degraded answer when OSV is unreachable.
  try {
    target[collection].createIndex(
      { updated_at: 1 },
      { name: "updated_at_ttl", expireAfterSeconds: 2592000 }
    );
    print("ttl index ensured (30d)");
  } catch (e) { print("ttl index skipped: " + e.codeName); }
  print("indexes ensured");
'

log "sharding is ready"
