#!/usr/bin/env bash
#
# Reactive autoscaler for the backend service.
#
# Why this exists: Docker Compose describes a fixed topology - it has no notion
# of "add capacity when busy". This closes that gap by watching HAProxy's own
# statistics and calling `docker compose up --scale`. It is deliberately small
# and readable; in production you would use a Kubernetes HorizontalPodAutoscaler
# or Nomad, which do the same loop with proper cooldowns and metrics.
#
# Scaling works at all only because the backend is a replicated service and
# HAProxy finds replicas over DNS (see server-template in haproxy.cfg).
#
# Usage:
#   ./scripts/autoscale.sh                 # run the control loop
#   ./scripts/autoscale.sh --once          # evaluate once and exit
set -uo pipefail

STATS_URL="${STATS_URL:-http://127.0.0.1:8404/;csv}"
STATS_USER="${STATS_USER:-admin}"
STATS_PASSWORD="${HAPROXY_STATS_PASSWORD:-changeme}"

# Default floor is 1: idle capacity is pure cost, and scaling up is fast.
MIN_REPLICAS="${MIN_REPLICAS:-1}"
MAX_REPLICAS="${MAX_REPLICAS:-12}"
# Sessions per replica. Above the high mark we add capacity, below the low mark
# we give it back.
SCALE_UP_AT="${SCALE_UP_AT:-8}"
SCALE_DOWN_AT="${SCALE_DOWN_AT:-2}"
INTERVAL="${INTERVAL:-15}"
COOLDOWN="${COOLDOWN:-60}"

last_action=0

log() { echo "$(date '+%H:%M:%S') [autoscale] $*"; }

current_replicas() {
    docker compose ps -q backend 2>/dev/null | grep -c . || echo 0
}

# Current sessions on the backend pool, from HAProxy's own accounting.
current_sessions() {
    curl -s --max-time 5 -u "$STATS_USER:$STATS_PASSWORD" "$STATS_URL" \
        | awk -F, '$1=="flaskservers" && $2=="BACKEND" {print $5; exit}'
}

healthy_servers() {
    curl -s --max-time 5 -u "$STATS_USER:$STATS_PASSWORD" "$STATS_URL" \
        | awk -F, '$1=="flaskservers" && $2!="BACKEND" && $18=="UP" {n++} END {print n+0}'
}

scale_to() {
    local target=$1
    log "scaling backend -> $target replicas"
    # --no-deps is essential: without it, `up --scale` re-runs the whole
    # dependency chain (including the one-shot Mongo init containers) on every
    # scaling action, which is slow and can fail the command outright.
    # --no-recreate leaves existing containers alone, so scaling does not
    # restart healthy replicas (and does not drop the current leader).
    if docker compose up -d --no-deps --no-recreate --scale "backend=$target" backend >/dev/null 2>&1; then
        last_action=$(date +%s)
        log "scaled to $target"
    else
        log "ERROR: scale command failed"
    fi
}

evaluate() {
    local replicas sessions healthy per_replica now target
    replicas=$(current_replicas)
    sessions=$(current_sessions)
    healthy=$(healthy_servers)

    if [ -z "$sessions" ]; then
        log "cannot read HAProxy stats (check HAPROXY_STATS_PASSWORD)"
        return
    fi
    if [ "$replicas" -eq 0 ]; then
        log "no backend replicas running"
        return
    fi

    per_replica=$(( sessions / replicas ))
    log "replicas=$replicas healthy=$healthy sessions=$sessions (${per_replica}/replica)"

    now=$(date +%s)
    if [ $(( now - last_action )) -lt "$COOLDOWN" ]; then
        log "in cooldown, holding"
        return
    fi

    target=$replicas
    if [ "$per_replica" -ge "$SCALE_UP_AT" ] && [ "$replicas" -lt "$MAX_REPLICAS" ]; then
        # Demand-driven, not blind doubling: from 1 replica a real spike would
        # otherwise need several cooldown cycles to reach capacity. Take
        # whichever is larger - double, or the replicas the load actually needs.
        local needed=$(( (sessions + SCALE_UP_AT - 1) / SCALE_UP_AT ))   # ceil
        target=$(( replicas * 2 ))
        [ "$needed" -gt "$target" ] && target=$needed
        [ "$target" -gt "$MAX_REPLICAS" ] && target=$MAX_REPLICAS
    elif [ "$per_replica" -le "$SCALE_DOWN_AT" ] && [ "$replicas" -gt "$MIN_REPLICAS" ]; then
        # Shrink gently: scaling down too eagerly causes flapping.
        target=$(( replicas - 1 ))
    fi

    [ "$target" -ne "$replicas" ] && scale_to "$target"
}

if [ "${1:-}" = "--once" ]; then
    evaluate
    exit 0
fi

log "watching HAProxy; min=$MIN_REPLICAS max=$MAX_REPLICAS up@${SCALE_UP_AT}/replica down@${SCALE_DOWN_AT}/replica"
trap 'log "stopped"; exit 0' INT TERM
while true; do
    evaluate
    sleep "$INTERVAL"
done
