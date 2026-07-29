#!/usr/bin/env bash
#
# Integration test: proves the cluster actually tolerates failure.
#
# "We run ZooKeeper" is a claim. This script is the evidence:
#   1. exactly one backend holds leadership at a time
#   2. killing the leader elects a new one, quickly
#   3. scans keep succeeding while a backend is down (HAProxy ejects it)
#   4. the recovered node rejoins without producing a second leader
#
# Usage: ./tests/integration/failover_test.sh
set -uo pipefail

URL="${CODEGUARD_URL:-http://127.0.0.1:80}"
MAX_FAILOVER_SECONDS="${MAX_FAILOVER_SECONDS:-30}"

# The backend is a replicated service, so replica names are assigned at run
# time - discover them instead of hardcoding backend1..backend4.
backends() {
    docker compose ps --format '{{.Name}}' backend 2>/dev/null
}

pass=0
fail=0

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    OK=$'\033[1;32m'; BAD=$'\033[1;31m'; DIM=$'\033[2m'; B=$'\033[1m'; ACC=$'\033[1;36m'; R=$'\033[0m'
else
    OK=""; BAD=""; DIM=""; B=""; ACC=""; R=""
fi

check() {
    if [ "$1" = "0" ]; then
        printf '  %s✓ PASS%s  %s\n' "$OK" "$R" "$2"; pass=$((pass + 1))
    else
        printf '  %s✗ FAIL%s  %s %s\n' "$BAD" "$R" "$2" "${3:+-> $3}"; fail=$((fail + 1))
    fi
}

note() { printf '        %s%s%s\n' "$DIM" "$1" "$R"; }
head1() { printf '%s[%s]%s %s%s%s\n' "$ACC" "$1" "$R" "$B" "$2" "$R"; }

is_leader() {
    docker exec "$1" python -c "
import json,sys,urllib.request
d = json.load(urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=3))
sys.exit(0 if d['leader'] else 1)" >/dev/null 2>&1
}

leaders() {
    local found=()
    while read -r b; do
        [ -z "$b" ] && continue
        docker ps --format '{{.Names}}' | grep -qx "$b" || continue
        is_leader "$b" && found+=("$b")
    done < <(backends)
    echo "${found[@]:-}"
}

scan_ok() {
    local code
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 -X POST "$URL/scan" \
        -H 'Content-Type: application/json' \
        -d '{"dependencies":["flask==2.2.2"]}')
    [ "$code" = "200" ]
}

printf '%scodeguard failover test%s\n' "$B" "$R"
echo

# The stack defaults to a single replica, which has nothing to fail over to.
# Scale up first so the test is actually exercising election, not startup.
REQUIRED_REPLICAS="${REQUIRED_REPLICAS:-3}"
current_replicas=$(backends | grep -c . || true)
if [ "$current_replicas" -lt "$REQUIRED_REPLICAS" ]; then
    echo "[0] scaling backend $current_replicas -> $REQUIRED_REPLICAS for the test"
    docker compose up -d --no-deps --no-recreate --scale "backend=$REQUIRED_REPLICAS" backend >/dev/null 2>&1
    for _ in $(seq 1 30); do
        [ "$(backends | grep -c .)" -ge "$REQUIRED_REPLICAS" ] && break
        sleep 2
    done
    sleep 10   # let the new replicas register with ZooKeeper
    note "now $(backends | grep -c .) replicas"
    echo
fi

head1 1 "exactly one leader at steady state"
read -ra current <<< "$(leaders)"
check "$([ ${#current[@]} -eq 1 ] && echo 0 || echo 1)" \
      "one leader elected" "found: ${current[*]:-none}"
original="${current[0]:-}"
[ -z "$original" ] && { echo "no leader - aborting"; exit 1; }
note "leader is $original"
echo

head1 2 "leadership moves when the leader dies"
docker stop "$original" >/dev/null 2>&1
start=$(date +%s)
new=""
for _ in $(seq 1 "$MAX_FAILOVER_SECONDS"); do
    read -ra candidates <<< "$(leaders)"
    if [ ${#candidates[@]} -eq 1 ] && [ "${candidates[0]}" != "$original" ]; then
        new="${candidates[0]}"; break
    fi
    sleep 1
done
elapsed=$(( $(date +%s) - start ))
check "$([ -n "$new" ] && echo 0 || echo 1)" \
      "new leader elected within ${MAX_FAILOVER_SECONDS}s" "took ${elapsed}s"
[ -n "$new" ] && note "new leader is $new (${elapsed}s)"
echo

head1 3 "scans keep working with a backend down"
ok=0
for _ in $(seq 1 8); do scan_ok && ok=$((ok + 1)); done
check "$([ "$ok" -eq 8 ] && echo 0 || echo 1)" "8/8 scans succeeded" "$ok/8 succeeded"
echo

head1 4 "recovered node rejoins without a split brain"
docker start "$original" >/dev/null 2>&1
sleep 15
read -ra final <<< "$(leaders)"
check "$([ ${#final[@]} -eq 1 ] && echo 0 || echo 1)" \
      "still exactly one leader after recovery" "found: ${final[*]:-none}"
note "leader is ${final[0]:-none}"
echo

if [ "$fail" -eq 0 ]; then printf '%s%d passed, %d failed%s\n' "$OK" "$pass" "$fail" "$R"; else printf '%s%d passed, %d failed%s\n' "$BAD" "$pass" "$fail" "$R"; fi
[ "$fail" -eq 0 ] || exit 1
