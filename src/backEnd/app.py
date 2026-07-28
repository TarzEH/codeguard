"""Flask application factory."""
import logging

from flask import Flask, jsonify, request

import config
import db
import refresh
from scanner import ScanError, Scanner

logger = logging.getLogger(__name__)


def create_app(coordinator=None, scanner=None):
    app = Flask(__name__)
    scanner = scanner or Scanner()

    @app.post("/scan")
    def scan():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or "dependencies" not in payload:
            return jsonify(error="body must be JSON containing a 'dependencies' list"), 400
        dependencies = payload["dependencies"]
        if not isinstance(dependencies, (list, str)):
            return jsonify(error="'dependencies' must be a list of requirement strings"), 400

        try:
            result = scanner.scan(dependencies)
        except ScanError as error:
            # Fail closed. An unanswered scan is an error, never a clean result.
            logger.warning("scan failed: %s", error)
            return jsonify(error=f"scan failed, results are unknown: {error}"), 503
        except Exception as error:  # noqa: BLE001
            logger.exception("unexpected scan failure")
            return jsonify(error=f"scan failed, results are unknown: {error}"), 500

        result["node"] = config.NODE_ID
        return jsonify(result), 200

    @app.get("/health")
    def health():
        """Liveness - what HAProxy checks. Stays 200 while the process can serve.

        Mongo state is reported but does not fail the check: a cache outage
        still lets us answer from upstream, and dropping every backend out of
        the pool would replace a clear 503 from /scan with an opaque one.
        """
        try:
            db.ping()
            mongo = "ok"
        except Exception as error:  # noqa: BLE001
            mongo = f"unavailable: {error}"

        return jsonify(
            status="ok",
            node=config.NODE_ID,
            leader=bool(coordinator.is_leader) if coordinator else None,
            zookeeper=_zk_status(coordinator),
            mongo=mongo,
            refresh=refresh.state,
        ), 200

    @app.get("/ready")
    def ready():
        """Deep check for humans and CI: 503 unless dependencies are actually usable."""
        try:
            db.ping()
        except Exception as error:  # noqa: BLE001
            return jsonify(status="not-ready", mongo=str(error)), 503
        return jsonify(status="ready", node=config.NODE_ID), 200

    @app.post("/test")
    def test():
        """No-op endpoint retained for the load-test scripts."""
        return jsonify([]), 200

    return app


def _zk_status(coordinator):
    if coordinator is None:
        return "disabled"
    connected = coordinator.connected
    if connected is None:
        return "disabled"
    return "connected" if connected else "disconnected"
