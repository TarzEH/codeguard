"""Cluster coordination: one ZooKeeper connection, shared by election + rate limiting."""
import logging
import threading

import config
from coordination.election import LeaderElection
from coordination.ratelimit import DistributedRateLimiter, LocalRateLimiter

logger = logging.getLogger(__name__)


class Coordinator:
    """Owns the ZooKeeper session and everything built on top of it.

    Degrades cleanly: with ZK_ENABLED=false (tests, single-node dev) the node
    considers itself leader and uses a process-local rate limiter, so the rest
    of the code never needs to branch on whether ZooKeeper is present.
    """

    def __init__(self):
        self._zk = None
        self._election = None
        self._standalone = not config.ZK_ENABLED
        self.rate_limiter = LocalRateLimiter(
            config.UPSTREAM_RATE_LIMIT,
            config.UPSTREAM_RATE_WINDOW_SECONDS,
            config.UPSTREAM_RATE_WAIT_SECONDS,
        )

    def start(self, on_elected=None):
        if self._standalone:
            logger.warning("ZK_ENABLED=false - running standalone, this node is always leader")
            if on_elected:
                threading.Thread(
                    target=on_elected, args=(threading.Event(),),
                    name="standalone-leader", daemon=True,
                ).start()
            return

        from kazoo.client import KazooClient

        self._zk = KazooClient(
            hosts=config.ZK_HOSTS,
            timeout=config.ZK_TIMEOUT_SECONDS,
        )
        self._zk.start_async()  # non-blocking: the app must serve /health even if ZK is slow
        logger.info("zookeeper session starting against %s", config.ZK_HOSTS)

        self.rate_limiter = DistributedRateLimiter(
            self._zk,
            config.ZK_RATELIMIT_PATH,
            config.UPSTREAM_RATE_LIMIT,
            config.UPSTREAM_RATE_WINDOW_SECONDS,
            config.UPSTREAM_RATE_WAIT_SECONDS,
        )

        self._election = LeaderElection(
            self._zk, config.ZK_ELECTION_PATH, config.NODE_ID, on_elected
        )
        self._election.start()

    @property
    def is_leader(self):
        if self._standalone:
            return True
        return bool(self._election and self._election.is_leader)

    @property
    def connected(self):
        if self._standalone:
            return None  # not applicable
        return bool(self._zk and self._zk.connected)

    def stop(self):
        if self._election:
            self._election.stop()
        if self._zk:
            try:
                self._zk.stop()
                self._zk.close()
            except Exception as error:  # noqa: BLE001 - shutdown must never raise
                logger.warning("error closing zookeeper: %s", error)
