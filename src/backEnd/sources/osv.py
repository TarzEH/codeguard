"""OSV.dev client - the primary vulnerability source.

Why OSV instead of the NVD keyword search the project used before:
  * version aware  - answers "is THIS version affected", not "does some CVE
                     description happen to contain this word"
  * batched        - /v1/querybatch takes every dependency in one request, so a
                     20 package requirements.txt costs 1 request, not 20
  * no API key     - and no 5-requests-per-30-seconds public throttle
  * broader        - aggregates GitHub Advisories, PyPI advisories and NVD

Request strategy: /v1/querybatch tells us *which* packages are affected (one
request for the whole scan). Only for those packages do we call /v1/query,
which returns the full advisory objects in a single call per package. Clean
packages cost no follow-up request at all.
"""
import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

logger = logging.getLogger(__name__)

# Ordering used to pick the worst severity of a package.
SEVERITY_ORDER = {"UNKNOWN": 0, "LOW": 1, "MODERATE": 2, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def _build_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=20)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "codeguard/2.0"})
    return session


_session = _build_session()


class OsvError(RuntimeError):
    """Raised when OSV cannot be queried. Never swallowed into an empty result."""


def _package_query(name, version):
    query = {"package": {"name": name, "ecosystem": config.OSV_ECOSYSTEM}}
    if version:
        query["version"] = version
    return query


def query_batch(packages, rate_limiter=None):
    """packages: list of (name, version). Returns a list of ID-lists, aligned by index."""
    if not packages:
        return []

    results = []
    for start in range(0, len(packages), config.OSV_BATCH_SIZE):
        chunk = packages[start:start + config.OSV_BATCH_SIZE]
        body = {"queries": [_package_query(n, v) for n, v in chunk]}
        if rate_limiter:
            rate_limiter.acquire()
        try:
            response = _session.post(
                f"{config.OSV_API_URL}/v1/querybatch",
                json=body,
                timeout=config.HTTP_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise OsvError(f"OSV querybatch failed: {error}") from error

        chunk_results = payload.get("results", [])
        if len(chunk_results) != len(chunk):
            raise OsvError(
                f"OSV returned {len(chunk_results)} results for {len(chunk)} queries"
            )
        for entry in chunk_results:
            # A package with no known vulnerabilities comes back as {}, not
            # {"vulns": []} - treating that as an error would break every clean scan.
            results.append([v["id"] for v in (entry or {}).get("vulns", [])])
    return results


def query_package(name, version, rate_limiter=None):
    """Full advisory objects for one package. Returns a list of normalised dicts."""
    if rate_limiter:
        rate_limiter.acquire()
    try:
        response = _session.post(
            f"{config.OSV_API_URL}/v1/query",
            json=_package_query(name, version),
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        raise OsvError(f"OSV query for {name} failed: {error}") from error

    return [normalise_vulnerability(v) for v in (payload or {}).get("vulns", [])]


def normalise_vulnerability(vuln):
    """Trim an OSV advisory down to what a developer actually needs to act."""
    database_specific = vuln.get("database_specific") or {}
    severity = (database_specific.get("severity") or "UNKNOWN").upper()

    cvss = None
    for entry in vuln.get("severity") or []:
        if entry.get("type", "").startswith("CVSS"):
            cvss = entry.get("score")
            break

    # CVE ids live in aliases; surface them because that is what people search.
    aliases = vuln.get("aliases") or []
    cves = [a for a in aliases if a.upper().startswith("CVE-")]

    return {
        "id": vuln.get("id"),
        "cves": cves,
        "aliases": aliases,
        "severity": severity,
        "cvss": cvss,
        "summary": vuln.get("summary") or vuln.get("details", "")[:200] or None,
        "fixed_in": _fixed_versions(vuln),
        "references": [r.get("url") for r in (vuln.get("references") or [])][:3],
    }


def _fixed_versions(vuln):
    """The versions that resolve the advisory - the single most actionable field."""
    fixed = []
    for affected in vuln.get("affected") or []:
        for range_entry in affected.get("ranges") or []:
            # GIT ranges express fixes as commit SHAs, which are useless to
            # someone pinning a version in requirements.txt.
            if (range_entry.get("type") or "").upper() == "GIT":
                continue
            for event in range_entry.get("events") or []:
                if "fixed" in event:
                    fixed.append(event["fixed"])
    # dict.fromkeys keeps first-seen order while de-duplicating
    return list(dict.fromkeys(fixed))


def max_severity(vulnerabilities):
    if not vulnerabilities:
        return "NONE"
    return max(
        (v.get("severity", "UNKNOWN") for v in vulnerabilities),
        key=lambda s: SEVERITY_ORDER.get(s, 0),
    )
