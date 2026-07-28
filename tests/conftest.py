"""Shared fixtures. No Docker, no network, no MongoDB - everything is faked."""
import os

# Must be set before `config` is imported anywhere.
os.environ.setdefault("ZK_ENABLED", "false")
os.environ.setdefault("NVD_FALLBACK_ENABLED", "false")
os.environ.setdefault("CACHE_TTL_SECONDS", "3600")

from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402


class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, n):
        return FakeCursor(self._docs[:n])

    def __iter__(self):
        return iter(self._docs)


class FakeCollection:
    """Just enough of a pymongo collection for the scanner and refresh job."""

    def __init__(self):
        self.store = {}
        self.reads = 0
        self.fail_on_read = False

    def find(self, query=None, projection=None):
        self.reads += 1
        if self.fail_on_read:
            raise RuntimeError("cache unavailable")
        query = query or {}
        docs = list(self.store.values())
        if "_id" in query and "$in" in query["_id"]:
            wanted = set(query["_id"]["$in"])
            docs = [d for d in docs if d["_id"] in wanted]
        if "updated_at" in query and "$lt" in query["updated_at"]:
            cutoff = query["updated_at"]["$lt"]
            docs = [d for d in docs if d.get("updated_at") and d["updated_at"] < cutoff]
        # Return copies so callers cannot mutate the "database".
        return FakeCursor([dict(d) for d in docs])

    def bulk_write(self, operations, ordered=True):
        for operation in operations:
            doc = dict(getattr(operation, "_doc", {}).get("$set", {}))
            if doc.get("_id"):
                self.store[doc["_id"]] = doc
        return len(operations)

    def seed(self, doc, age_seconds=0):
        doc = dict(doc)
        doc["updated_at"] = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        self.store[doc["_id"]] = doc
        return doc


@pytest.fixture
def cache(monkeypatch):
    import db

    collection = FakeCollection()
    monkeypatch.setattr(db, "get_cache_collection", lambda: collection)
    return collection


@pytest.fixture
def osv_stub(monkeypatch):
    """Controllable stand-in for the OSV API."""
    import sources.osv as osv_module

    class Stub:
        def __init__(self):
            self.vulnerable = {}     # package name -> list of normalised vulns
            self.batch_calls = 0
            self.package_calls = 0
            self.error = None

        def query_batch(self, packages, rate_limiter=None):
            self.batch_calls += 1
            if self.error:
                raise osv_module.OsvError(self.error)
            return [[v["id"] for v in self.vulnerable.get(name, [])] for name, _ in packages]

        def query_package(self, name, version, rate_limiter=None):
            self.package_calls += 1
            if self.error:
                raise osv_module.OsvError(self.error)
            return list(self.vulnerable.get(name, []))

    stub = Stub()
    monkeypatch.setattr(osv_module, "query_batch", stub.query_batch)
    monkeypatch.setattr(osv_module, "query_package", stub.query_package)
    return stub


def vuln(vuln_id, severity="HIGH", cve=None, fixed=None):
    return {
        "id": vuln_id,
        "cves": [cve] if cve else [],
        "aliases": [cve] if cve else [],
        "severity": severity,
        "cvss": None,
        "summary": "test advisory",
        "fixed_in": fixed or [],
        "references": [],
    }
