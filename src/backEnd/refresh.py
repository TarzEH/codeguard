"""The leader-only job. This is what makes leader election meaningful here.

Every replica can serve scans, but exactly one replica may refresh the shared
vulnerability cache: with four replicas refreshing independently we would make
4x the upstream calls and race each other's writes. "Leader" in this system
means precisely "the replica that owns cache refresh".
"""
import logging
import threading
from datetime import datetime, timedelta, timezone

import config
import db

logger = logging.getLogger(__name__)

# Exposed on /health so leadership is observable from outside.
state = {
    "last_refresh_at": None,
    "last_refresh_count": 0,
    "last_refresh_error": None,
    "refresh_runs": 0,
}
_lock = threading.Lock()


def stale_specs(limit=None):
    """Cache entries older than the TTL, oldest first."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=config.CACHE_TTL_SECONDS)
    cursor = (
        db.get_cache_collection()
        .find({"updated_at": {"$lt": cutoff}}, {"package": 1, "version": 1})
        .sort("updated_at", 1)
        .limit(limit or config.REFRESH_BATCH_SIZE)
    )
    return [(doc["package"], doc.get("version")) for doc in cursor if doc.get("package")]


def refresh_once(scanner):
    specs = stale_specs()
    if not specs:
        return 0
    logger.info("refreshing %d stale cache entries", len(specs))
    scanner.refresh(specs)
    return len(specs)


def run_refresh_loop(scanner, stop_event):
    """Runs for the duration of a leadership term; returns when it ends."""
    logger.info("cache refresh loop started - this node is the leader")
    if not config.REFRESH_ENABLED:
        logger.info("REFRESH_ENABLED=false - holding leadership without refreshing")
        stop_event.wait()
        return

    # wait() first, so a leadership flap does not trigger a refresh storm.
    while not stop_event.wait(config.REFRESH_INTERVAL_SECONDS):
        try:
            count = refresh_once(scanner)
            with _lock:
                state["last_refresh_at"] = datetime.now(timezone.utc).isoformat()
                state["last_refresh_count"] = count
                state["last_refresh_error"] = None
                state["refresh_runs"] += 1
        except Exception as error:  # noqa: BLE001 - a bad run must not end the term
            logger.exception("cache refresh failed")
            with _lock:
                state["last_refresh_error"] = str(error)
    logger.info("cache refresh loop stopped - leadership ended")


def make_leader_job(scanner):
    def job(stop_event):
        run_refresh_loop(scanner, stop_event)
    return job
