"""ZooKeeper leader election.

The project's original implementation hand-rolled the ephemeral+sequential
znode algorithm (each node watching its predecessor). That algorithm was
correct, but it never ran: the signal handler was invoked instead of
registered, the ZK host was hardcoded to localhost while the container was
named `zoo`, and - most importantly - nothing ever consumed is_leader().

This uses kazoo's Election recipe, which implements the same algorithm and is
battle tested, and wires the result to a real job (see refresh.py). Leadership
here means exactly one thing: "this replica owns the cache refresh".
"""
import logging
import threading

from kazoo.client import KazooState
from kazoo.recipe.election import Election

logger = logging.getLogger(__name__)


class LeaderElection:
    def __init__(self, zk, path, identifier, on_elected=None):
        self._zk = zk
        self._path = path
        self._identifier = identifier
        self._on_elected = on_elected
        self._election = Election(zk, path, identifier)
        self._is_leader = False
        self._shutdown = threading.Event()
        self._term_stop = threading.Event()
        self._thread = None

    def start(self):
        self._zk.add_listener(self._on_connection_change)
        self._thread = threading.Thread(target=self._contend, name="leader-election", daemon=True)
        self._thread.start()

    def _on_connection_change(self, state):
        # A lost or suspended session means our ephemeral znode may be gone, so
        # another node can legally take over. Stand down immediately rather than
        # risk two leaders running the refresh job at once.
        if state in (KazooState.LOST, KazooState.SUSPENDED):
            if self._is_leader:
                logger.warning("zookeeper session %s - standing down as leader", state)
            self._term_stop.set()
        else:
            logger.info("zookeeper connection state: %s", state)

    def _contend(self):
        while not self._shutdown.is_set():
            try:
                # Blocks until this node wins, then calls _lead.
                self._election.run(self._lead)
            except Exception as error:  # noqa: BLE001 - keep contending forever
                logger.warning("election error, retrying: %s", error)
                self._shutdown.wait(5)

    def _lead(self):
        self._term_stop = threading.Event()
        self._is_leader = True
        logger.info("elected leader (node=%s)", self._identifier)
        try:
            if self._on_elected:
                # Blocks for the duration of this leadership term.
                self._on_elected(self._term_stop)
            else:
                self._term_stop.wait()
        except Exception as error:  # noqa: BLE001 - never take the process down
            logger.exception("leader job failed: %s", error)
        finally:
            self._is_leader = False
            logger.info("released leadership (node=%s)", self._identifier)

    @property
    def is_leader(self):
        return self._is_leader

    def stop(self):
        self._shutdown.set()
        self._term_stop.set()
        try:
            self._election.cancel()
        except Exception:  # noqa: BLE001
            pass
