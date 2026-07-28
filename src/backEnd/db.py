"""MongoDB access.

The client is a process-wide singleton: MongoClient maintains its own
connection pool and is thread safe, so building one per request (as the
original code did) throws away pooling and leaks sockets under load.
"""
import logging
import threading

from pymongo import MongoClient

import config

logger = logging.getLogger(__name__)

_client = None
_lock = threading.Lock()


def get_client():
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                logger.info("connecting to mongo at %s", config.MONGO_URI)
                _client = MongoClient(
                    config.MONGO_URI,
                    serverSelectionTimeoutMS=config.MONGO_TIMEOUT_MS,
                    connectTimeoutMS=config.MONGO_TIMEOUT_MS,
                    retryWrites=True,
                )
    return _client


def get_db():
    return get_client()[config.MONGO_DB]


def get_cache_collection():
    return get_db()[config.CACHE_COLLECTION]


def ping():
    """Raises if MongoDB is unreachable. Used by the health endpoint."""
    get_client().admin.command("ping")


def close():
    global _client
    with _lock:
        if _client is not None:
            _client.close()
            _client = None
