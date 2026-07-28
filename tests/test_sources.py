"""Parsing of real upstream payload shapes."""
import pytest

from sources import osv


def test_empty_result_object_means_no_vulnerabilities(monkeypatch):
    """OSV returns {} - not {"vulns": []} - for a clean package.

    Treating that as malformed would break every clean scan.
    """
    class FakeResponse:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"results": [{}, {"vulns": [{"id": "GHSA-1"}]}]}

    monkeypatch.setattr(osv._session, "post", lambda *a, **k: FakeResponse())
    assert osv.query_batch([("clean", "1.0"), ("flask", "2.2.2")]) == [[], ["GHSA-1"]]


def test_result_count_mismatch_is_an_error(monkeypatch):
    """Misaligned results would attribute one package's vulnerabilities to another."""
    class FakeResponse:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"results": [{}]}

    monkeypatch.setattr(osv._session, "post", lambda *a, **k: FakeResponse())
    with pytest.raises(osv.OsvError):
        osv.query_batch([("a", "1.0"), ("b", "1.0")])


def test_transport_failure_raises_rather_than_returning_empty(monkeypatch):
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(osv._session, "post", boom)
    with pytest.raises(osv.OsvError):
        osv.query_batch([("flask", "2.2.2")])


def test_normalise_extracts_the_actionable_fields():
    raw = {
        "id": "GHSA-m2qf-hxjv-5gpq",
        "aliases": ["CVE-2023-30861", "PYSEC-2023-62"],
        "summary": "Flask may disclose a permanent session cookie",
        "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L"}],
        "database_specific": {"severity": "HIGH"},
        "affected": [{"ranges": [
            {"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "2.2.5"}]},
            # GIT ranges give commit SHAs, which nobody can put in requirements.txt
            {"type": "GIT", "events": [{"introduced": "0"}, {"fixed": "70f906c51ce49c4"}]},
        ]}],
        "references": [{"url": "https://example.test/advisory"}],
    }
    result = osv.normalise_vulnerability(raw)

    assert result["cves"] == ["CVE-2023-30861"]
    assert result["severity"] == "HIGH"
    assert result["cvss"] == "CVSS:3.1/AV:N/AC:L"
    assert result["fixed_in"] == ["2.2.5"], "commit SHAs must not leak into fixed versions"


def test_normalise_tolerates_a_minimal_advisory():
    result = osv.normalise_vulnerability({"id": "PYSEC-1"})
    assert result["severity"] == "UNKNOWN"
    assert result["cves"] == []
    assert result["fixed_in"] == []


@pytest.mark.parametrize("severities,expected", [
    (["LOW", "CRITICAL", "HIGH"], "CRITICAL"),
    (["LOW", "MODERATE"], "MODERATE"),
    (["UNKNOWN"], "UNKNOWN"),
    ([], "NONE"),
])
def test_max_severity(severities, expected):
    assert osv.max_severity([{"severity": s} for s in severities]) == expected
