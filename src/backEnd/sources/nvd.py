"""NVD fallback source - disabled by default.

Kept so the project can still demonstrate a second source, but deliberately
demoted from primary because its keyword search matches CVE *descriptions*
rather than package versions: searching "requests" returns every advisory whose
text mentions the word. Results from here are flagged with
`version_aware: false` so nobody mistakes them for a precise answer.

Public NVD allows 5 requests / 30s (50 with an API key), which is why every call
goes through the shared distributed rate limiter.
"""
import logging
from urllib.parse import urlencode

import requests

import config

logger = logging.getLogger(__name__)


class NvdError(RuntimeError):
    """Raised when NVD cannot be queried."""


def query_package(name, version=None, rate_limiter=None):
    """Best-effort keyword lookup. Version is ignored by the NVD keyword API."""
    if rate_limiter:
        rate_limiter.acquire()

    headers = {"User-Agent": "codeguard/2.0"}
    if config.NVD_API_KEY:
        headers["apiKey"] = config.NVD_API_KEY

    # urlencode matters: package names legitimately contain '+' and '.', which
    # silently corrupt the query when interpolated straight into the URL.
    url = f"{config.NVD_API_URL}?{urlencode({'keywordSearch': name})}"
    try:
        response = requests.get(url, headers=headers, timeout=config.HTTP_TIMEOUT_SECONDS)
    except requests.RequestException as error:
        raise NvdError(f"NVD request for {name} failed: {error}") from error

    if response.status_code == 403 or response.status_code == 429:
        raise NvdError(
            f"NVD rate limited (HTTP {response.status_code}). "
            "Set NVD_API_KEY or lower UPSTREAM_RATE_LIMIT."
        )
    if response.status_code != 200:
        # A non-200 is an unknown answer, never a clean one.
        raise NvdError(f"NVD returned HTTP {response.status_code} for {name}")

    try:
        payload = response.json()
    except ValueError as error:
        raise NvdError(f"NVD returned invalid JSON for {name}: {error}") from error

    vulnerabilities = []
    for item in payload.get("vulnerabilities", []):
        cve = item.get("cve", {})
        vulnerabilities.append({
            "id": cve.get("id"),
            "cves": [cve.get("id")] if cve.get("id") else [],
            "aliases": [],
            "severity": _severity(cve),
            "cvss": None,
            "summary": _description(cve),
            "fixed_in": [],
            "references": [],
            "version_aware": False,
        })
    return vulnerabilities


def _severity(cve):
    metrics = cve.get("metrics") or {}
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        entries = metrics.get(key) or []
        if entries:
            data = entries[0].get("cvssData") or {}
            return (data.get("baseSeverity") or "UNKNOWN").upper()
    return "UNKNOWN"


def _description(cve):
    for description in cve.get("descriptions") or []:
        if description.get("lang") == "en":
            return description.get("value", "")[:200]
    return None
