"""Core scan logic: dependency string -> vulnerability findings.

Replaces dependencyExecutor.py. Behaviour differences that matter:
  * version aware   - "flask==2.2.2" is matched against affected version ranges
  * fail closed     - an unreachable source raises; it never returns "clean"
  * per-dependency  - result state is never shared between loop iterations
  * cached          - answers are stored in the sharded Mongo collection and
                      refreshed in the background by the elected leader
"""
import logging
import re
from datetime import datetime, timedelta, timezone

from pymongo import UpdateOne

import config
import db
from sources import nvd, osv

logger = logging.getLogger(__name__)

# name[extras] followed by an optional version specifier
_REQUIREMENT_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*"
    r"(?:\[[^\]]*\])?\s*"
    r"(?:(?P<op>===|==|>=|<=|~=|!=|>|<)\s*(?P<version>[A-Za-z0-9][A-Za-z0-9._+!-]*))?"
)


def normalise_name(name):
    """PEP 503 normalisation, so Flask / flask / FLASK share one cache entry."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def parse_requirement(line):
    """Returns (name, version) or None if the line carries no scannable package.

    Only '==' yields a concrete version. For range specifiers we deliberately
    query the package as a whole rather than guessing which version is installed.
    """
    if not isinstance(line, str):
        return None
    line = line.split("#", 1)[0].strip()
    if not line or line.startswith("-") or "://" in line:
        return None

    match = _REQUIREMENT_RE.match(line)
    if not match:
        return None

    name = normalise_name(match.group("name"))
    if not name:
        return None
    version = match.group("version") if match.group("op") in ("==", "===") else None
    return name, version


def cache_key(name, version):
    return f"{config.OSV_ECOSYSTEM}:{name}:{version or '*'}"


class ScanError(RuntimeError):
    """No trustworthy answer could be produced. Surfaces as HTTP 500."""


class Scanner:
    def __init__(self, rate_limiter=None):
        self._rate_limiter = rate_limiter

    def set_rate_limiter(self, rate_limiter):
        """Injected after startup: the shared limiter needs a live ZK session."""
        self._rate_limiter = rate_limiter

    # -- public API ----------------------------------------------------------

    def scan(self, dependencies):
        warnings = []
        specs, unparsed = self._parse_all(dependencies)
        if unparsed:
            warnings.append(f"ignored {len(unparsed)} unrecognised entries: {', '.join(unparsed[:5])}")

        resolved = self._resolve(specs, warnings) if specs else {}

        findings = []
        for name, version in specs:
            record = resolved.get(cache_key(name, version))
            if not record or not record.get("vulnerabilities"):
                continue
            findings.append({
                "package": name,
                "version": version,
                "vulnerability_count": len(record["vulnerabilities"]),
                "max_severity": record.get("max_severity", "UNKNOWN"),
                "source": record.get("source", "unknown"),
                "vulnerabilities": record["vulnerabilities"],
            })

        findings.sort(
            key=lambda f: (-osv.SEVERITY_ORDER.get(f["max_severity"], 0), f["package"])
        )
        return {
            "scanned": len(specs),
            "vulnerable": len(findings),
            "findings": findings,
            "warnings": warnings,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }

    def refresh(self, specs):
        """Force a re-fetch, ignoring cache freshness. Used by the elected leader."""
        warnings = []
        self._resolve(specs, warnings, force=True)
        return warnings

    # -- internals -----------------------------------------------------------

    def _parse_all(self, dependencies):
        if isinstance(dependencies, str):
            dependencies = [dependencies]
        specs, unparsed, seen = [], [], set()
        for raw in dependencies or []:
            parsed = parse_requirement(raw)
            if not parsed:
                if isinstance(raw, str) and raw.strip():
                    unparsed.append(raw.strip())
                continue
            if parsed in seen:
                continue
            seen.add(parsed)
            specs.append(parsed)
        return specs, unparsed

    def _resolve(self, specs, warnings, force=False):
        """Returns {cache_key: record} for every spec, fetching what is missing."""
        keys = [cache_key(n, v) for n, v in specs]
        cached = {} if force else self._read_cache(keys, warnings)

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=config.CACHE_TTL_SECONDS)
        resolved, stale, missing = {}, {}, []
        for (name, version), key in zip(specs, keys):
            record = cached.get(key)
            if record and _updated_at(record) >= cutoff:
                record["source"] = "cache"
                resolved[key] = record
            else:
                if record:
                    stale[key] = record
                missing.append((name, version))

        if not missing:
            return resolved

        try:
            fetched = self._fetch(missing)
        except (osv.OsvError, nvd.NvdError) as error:
            # Upstream is down. Stale cache is better than nothing, but the
            # caller must be told the answer is not current.
            if stale and len(stale) == len(missing):
                warnings.append(f"upstream unavailable ({error}); served stale cached results")
                for key, record in stale.items():
                    record["source"] = "cache-stale"
                    resolved[key] = record
                return resolved
            raise ScanError(str(error)) from error

        self._write_cache(fetched)
        resolved.update(fetched)
        return resolved

    def _fetch(self, specs):
        """Query OSV for every spec, falling back to NVD only if configured."""
        try:
            return self._fetch_from_osv(specs)
        except osv.OsvError as error:
            if not config.NVD_FALLBACK_ENABLED:
                raise
            logger.warning("OSV failed (%s), falling back to NVD", error)
            return self._fetch_from_nvd(specs)

    def _fetch_from_osv(self, specs):
        id_lists = osv.query_batch(specs, self._rate_limiter)
        now = datetime.now(timezone.utc)
        records = {}
        for (name, version), ids in zip(specs, id_lists):
            vulnerabilities = []
            if ids:
                # Only affected packages need the detail call; clean ones cost nothing.
                vulnerabilities = osv.query_package(name, version, self._rate_limiter)
            records[cache_key(name, version)] = {
                "_id": cache_key(name, version),
                "ecosystem": config.OSV_ECOSYSTEM,
                "package": name,
                "version": version,
                "vulnerabilities": vulnerabilities,
                "max_severity": osv.max_severity(vulnerabilities),
                "source": "osv",
                "updated_at": now,
            }
        return records

    def _fetch_from_nvd(self, specs):
        now = datetime.now(timezone.utc)
        records = {}
        for name, version in specs:
            vulnerabilities = nvd.query_package(name, version, self._rate_limiter)
            records[cache_key(name, version)] = {
                "_id": cache_key(name, version),
                "ecosystem": config.OSV_ECOSYSTEM,
                "package": name,
                "version": version,
                "vulnerabilities": vulnerabilities,
                "max_severity": osv.max_severity(vulnerabilities),
                "source": "nvd",
                "updated_at": now,
            }
        return records

    def _read_cache(self, keys, warnings):
        try:
            collection = db.get_cache_collection()
            return {doc["_id"]: doc for doc in collection.find({"_id": {"$in": keys}})}
        except Exception as error:  # noqa: BLE001
            # A cache outage must degrade to "fetch from upstream", not to failure.
            logger.warning("cache read failed: %s", error)
            warnings.append("vulnerability cache unavailable, queried upstream directly")
            return {}

    def _write_cache(self, records):
        if not records:
            return
        try:
            db.get_cache_collection().bulk_write(
                [UpdateOne({"_id": k}, {"$set": v}, upsert=True) for k, v in records.items()],
                ordered=False,
            )
        except Exception as error:  # noqa: BLE001
            logger.warning("cache write failed: %s", error)


def _updated_at(record):
    value = record.get("updated_at")
    if not isinstance(value, datetime):
        return datetime.min.replace(tzinfo=timezone.utc)
    # pymongo returns naive UTC datetimes unless configured otherwise.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
