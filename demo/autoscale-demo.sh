#!/usr/bin/env bash
#
# Visualises the autoscaler: start at one replica, apply load, watch the
# cluster grow, stop the load, watch it shrink back.
#
#   ./demo/autoscale-demo.sh
#
# Used by demo/autoscale.tape to record assets/demo-autoscale.gif.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

URL="${CODEGUARD_URL:-http://127.0.0.1:80}"
CONNECTIONS="${CONNECTIONS:-40}"
LOAD_SECONDS="${LOAD_SECONDS:-35}"
DRAIN_SECONDS="${DRAIN_SECONDS:-115}"
TICK="${TICK:-5}"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    B=$'\033[1m'; DIM=$'\033[2m'; ACC=$'\033[1;36m'; OK=$'\033[1;32m'
    UP=$'\033[1;33m'; R=$'\033[0m'
else
    B=""; DIM=""; ACC=""; OK=""; UP=""; R=""
fi

replicas() { docker compose ps -q backend 2>/dev/null | grep -c . || echo 0; }

bar() {
    local n=$1 out='' i
    for (( i = 0; i < n; i++ )); do out+="█"; done
    printf '%s' "$out"
}

row() {
    local elapsed=$1 phase=$2 colour=$3 n
    n=$(replicas)
    printf '  %st=%3ss%s  %s%-2s%s %s%s%s  %s%s%s\n' \
        "$DIM" "$elapsed" "$R" "$B" "$n" "$R" "$colour" "$(bar "$n")" "$R" "$DIM" "$phase" "$R"
}

printf '\n  %scodeguard autoscaler%s  %s— replicas follow demand%s\n\n' "$B" "$R" "$DIM" "$R"
printf '  %sstarting state: %s replica%s\n' "$DIM" "$(replicas)" "$R"
printf '  %sapplying load: %s concurrent connections for %ss%s\n\n' \
    "$DIM" "$CONNECTIONS" "$LOAD_SECONDS" "$R"

# Background load. Each worker requests an unseen package so every scan is a
# genuine cache miss and holds a session open.
END=$(( $(date +%s) + LOAD_SECONDS ))
for _ in $(seq 1 "$CONNECTIONS"); do
    (
        while [ "$(date +%s)" -lt "$END" ]; do
            pkg="demo$(LC_ALL=C tr -dc 'a-z' </dev/urandom | head -c 8)"
            curl -s -o /dev/null --max-time 20 -X POST "$URL/scan" \
                -H 'Content-Type: application/json' \
                -d "{\"dependencies\":[\"${pkg}==1.0.0\"]}" 2>/dev/null
        done
    ) &
done
LOAD_PIDS=$(jobs -p)
# Only fires if the demo is interrupted; the normal path lets workers finish.
trap 'kill $LOAD_PIDS 2>/dev/null' INT TERM

elapsed=0
while [ "$elapsed" -lt "$LOAD_SECONDS" ]; do
    row "$elapsed" "under load" "$UP"
    sleep "$TICK"
    elapsed=$(( elapsed + TICK ))
done

# Workers exit on their own once END passes. Killing them makes bash print a
# job-termination notice (with the whole loop body) into the recording.
wait 2>/dev/null
printf '\n  %sload stopped%s\n\n' "$B" "$R"

drained=0
while [ "$drained" -lt "$DRAIN_SECONDS" ]; do
    row "$elapsed" "draining" "$ACC"
    [ "$(replicas)" -le 1 ] && break
    sleep "$TICK"
    elapsed=$(( elapsed + TICK ))
    drained=$(( drained + TICK ))
done

final=$(replicas)
printf '\n  %sback to %s replica%s - capacity released%s\n\n' \
    "$OK" "$final" "$([ "$final" = "1" ] || echo s)" "$R"
