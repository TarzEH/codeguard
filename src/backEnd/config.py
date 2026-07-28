"""Runtime configuration, driven entirely by environment variables.

Replaces the old hardcoded serverConfiguration.py so the same image can run in
docker-compose, CI and locally without editing source.
"""
import os
import socket


def _bool(name, default):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- identity ---------------------------------------------------------------
NODE_ID = os.environ.get("NODE_ID") or socket.gethostname()

# --- MongoDB ----------------------------------------------------------------
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://mongos:27017")
MONGO_DB = os.environ.get("MONGO_DB", "codeguard")
CACHE_COLLECTION = os.environ.get("CACHE_COLLECTION", "vulnerability_cache")
MONGO_TIMEOUT_MS = _int("MONGO_TIMEOUT_MS", 5000)

# How long a cached lookup stays trustworthy before it must be re-fetched.
CACHE_TTL_SECONDS = _int("CACHE_TTL_SECONDS", 6 * 3600)

# --- vulnerability sources --------------------------------------------------
# OSV is version-aware and supports batching, so it is the primary source.
OSV_API_URL = os.environ.get("OSV_API_URL", "https://api.osv.dev")
OSV_ECOSYSTEM = os.environ.get("OSV_ECOSYSTEM", "PyPI")
OSV_BATCH_SIZE = _int("OSV_BATCH_SIZE", 100)
HTTP_TIMEOUT_SECONDS = _int("HTTP_TIMEOUT_SECONDS", 20)

# NVD stays available as a fallback only. Its keyword search is not
# version-aware, so results are best-effort and labelled as such.
NVD_FALLBACK_ENABLED = _bool("NVD_FALLBACK_ENABLED", False)
NVD_API_URL = os.environ.get("NVD_API_URL", "https://services.nvd.nist.gov/rest/json/cves/2.0")
NVD_API_KEY = os.environ.get("NVD_API_KEY", "")

# --- ZooKeeper coordination -------------------------------------------------
ZK_ENABLED = _bool("ZK_ENABLED", True)
ZK_HOSTS = os.environ.get("ZK_HOSTS", "zoo1:2181,zoo2:2181,zoo3:2181")
ZK_TIMEOUT_SECONDS = _int("ZK_TIMEOUT_SECONDS", 10)
ZK_ELECTION_PATH = os.environ.get("ZK_ELECTION_PATH", "/codeguard/election")
ZK_RATELIMIT_PATH = os.environ.get("ZK_RATELIMIT_PATH", "/codeguard/ratelimit")

# Outbound budget SHARED by every backend replica. Upstream APIs rate limit per
# source IP, so a per-process limiter would let N replicas exceed it N times.
UPSTREAM_RATE_LIMIT = _int("UPSTREAM_RATE_LIMIT", 40)
UPSTREAM_RATE_WINDOW_SECONDS = _int("UPSTREAM_RATE_WINDOW_SECONDS", 30)
UPSTREAM_RATE_WAIT_SECONDS = _int("UPSTREAM_RATE_WAIT_SECONDS", 15)

# --- leader-only cache refresh ----------------------------------------------
REFRESH_ENABLED = _bool("REFRESH_ENABLED", True)
REFRESH_INTERVAL_SECONDS = _int("REFRESH_INTERVAL_SECONDS", 900)
REFRESH_BATCH_SIZE = _int("REFRESH_BATCH_SIZE", 100)
