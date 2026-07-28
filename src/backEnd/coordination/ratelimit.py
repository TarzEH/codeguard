"""Rate limiting for outbound calls to upstream vulnerability APIs.

Upstream APIs throttle per source IP, not per container. Four backend replicas
each running a private limiter would emit 4x the agreed rate and get the whole
deployment blocked - so the token bucket lives in ZooKeeper and is shared by
every replica.

The bucket is a single znode holding {tokens, ts}, updated with a
version-checked write (compare-and-swap). A concurrent writer causes
BadVersionError, which simply means "re-read and try again".
"""
import json
import logging
import random
import threading
import time

logger = logging.getLogger(__name__)


class RateLimitTimeout(RuntimeError):
    """Raised when the shared budget could not be obtained in time."""


class LocalRateLimiter:
    """Process-local token bucket. Used when ZooKeeper is disabled."""

    def __init__(self, rate, window_seconds, wait_seconds):
        self._rate = float(rate)
        self._window = float(window_seconds)
        self._wait = float(wait_seconds)
        self._tokens = float(rate)
        self._ts = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self):
        deadline = time.monotonic() + self._wait
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self._rate,
                    self._tokens + (now - self._ts) * (self._rate / self._window),
                )
                self._ts = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return True
            if time.monotonic() >= deadline:
                raise RateLimitTimeout("local rate limit budget exhausted")
            time.sleep(0.05)


class DistributedRateLimiter:
    """Token bucket shared across all replicas via a ZooKeeper znode."""

    def __init__(self, zk, path, rate, window_seconds, wait_seconds):
        self._zk = zk
        self._path = path
        self._rate = float(rate)
        self._window = float(window_seconds)
        self._wait = float(wait_seconds)
        # If ZooKeeper is unreachable we must not become unlimited, so fall back
        # to a local bucket rather than skipping the limit entirely.
        self._fallback = LocalRateLimiter(rate, window_seconds, wait_seconds)

    def _ensure_node(self):
        from kazoo.exceptions import NodeExistsError

        if self._zk.exists(self._path) is None:
            payload = json.dumps({"tokens": self._rate, "ts": time.time()}).encode()
            try:
                self._zk.create(self._path, payload, makepath=True)
            except NodeExistsError:
                pass  # another replica created it first, which is fine

    def acquire(self):
        from kazoo.exceptions import BadVersionError, KazooException

        if not self._zk.connected:
            logger.warning("zookeeper unavailable - using local rate limit budget")
            return self._fallback.acquire()

        deadline = time.monotonic() + self._wait
        try:
            self._ensure_node()
            while True:
                raw, stat = self._zk.get(self._path)
                now = time.time()
                try:
                    state = json.loads(raw.decode()) if raw else {}
                except (ValueError, UnicodeDecodeError):
                    state = {}
                tokens = float(state.get("tokens", self._rate))
                last = float(state.get("ts", now))

                # Refill for the time elapsed since the last update, capped at
                # the bucket size so an idle cluster cannot bank unlimited calls.
                tokens = min(self._rate, tokens + max(0.0, now - last) * (self._rate / self._window))

                if tokens >= 1:
                    payload = json.dumps({"tokens": tokens - 1, "ts": now}).encode()
                    try:
                        self._zk.set(self._path, payload, version=stat.version)
                        return True
                    except BadVersionError:
                        continue  # lost the race, re-read immediately

                if time.monotonic() >= deadline:
                    raise RateLimitTimeout(
                        f"shared upstream budget exhausted after {self._wait:.0f}s"
                    )
                # Jitter stops all replicas from waking in lockstep.
                time.sleep(0.05 + random.random() * 0.1)
        except KazooException as error:
            logger.warning("zookeeper rate limiter failed (%s) - using local budget", error)
            return self._fallback.acquire()
