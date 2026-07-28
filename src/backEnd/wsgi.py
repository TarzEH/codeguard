"""Gunicorn entrypoint: `gunicorn wsgi:app`.

The old code called app.run() at import time, which meant the Flask development
server was the production server. Gunicorn owns the socket now; this module
only wires the object graph together.

Runs with a single worker process and multiple threads on purpose: the workload
is I/O bound, and one process per container keeps exactly one participant per
replica in the leader election.
"""
import atexit
import logging
import os

import config
import refresh
from app import create_app
from coordination import Coordinator
from scanner import Scanner

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [" + config.NODE_ID + "] %(name)s: %(message)s",
)

scanner = Scanner()
coordinator = Coordinator()
coordinator.start(on_elected=refresh.make_leader_job(scanner))

# The distributed limiter only exists once the ZK session has been created.
scanner.set_rate_limiter(coordinator.rate_limiter)

atexit.register(coordinator.stop)

app = create_app(coordinator=coordinator, scanner=scanner)
