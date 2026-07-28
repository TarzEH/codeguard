import pytest

from conftest import vuln
from scanner import ScanError, Scanner, cache_key, parse_requirement


class TestParsing:
    @pytest.mark.parametrize("line,expected", [
        ("flask==2.2.2", ("flask", "2.2.2")),
        ("Flask==2.2.2", ("flask", "2.2.2")),          # PEP 503 normalisation
        ("zope.interface==5.0", ("zope-interface", "5.0")),
        ("requests[security]==2.28.1", ("requests", "2.28.1")),
        ("flask >= 1.0", ("flask", None)),             # range: scan the package, do not guess
        ("flask", ("flask", None)),
        ("  flask==2.2.2  # pinned", ("flask", "2.2.2")),
    ])
    def test_valid(self, line, expected):
        assert parse_requirement(line) == expected

    @pytest.mark.parametrize("line", [
        "", "   ", "# a comment", "-r other.txt", "--index-url https://x",
        "git+https://github.com/x/y.git", None,
    ])
    def test_ignored(self, line):
        assert parse_requirement(line) is None


class TestScan:
    def test_no_cross_dependency_contamination(self, cache, osv_stub):
        """The original bug: one match made every later dependency look vulnerable."""
        osv_stub.vulnerable = {"flask": [vuln("GHSA-1", cve="CVE-2023-30861")]}

        result = Scanner().scan(["flask==2.2.2", "totally-fake-pkg==1.0", "another-fake==2.0"])

        assert [f["package"] for f in result["findings"]] == ["flask"]
        assert result["scanned"] == 3
        assert result["vulnerable"] == 1

    def test_count_is_real_not_hardcoded(self, cache, osv_stub):
        osv_stub.vulnerable = {"requests": [vuln("A"), vuln("B"), vuln("C")]}
        result = Scanner().scan(["requests==2.28.1"])
        assert result["findings"][0]["vulnerability_count"] == 3

    def test_clean_scan_is_empty_not_an_error(self, cache, osv_stub):
        result = Scanner().scan(["totally-fake-pkg==1.0"])
        assert result["findings"] == []
        assert result["vulnerable"] == 0

    def test_clean_packages_cost_no_detail_call(self, cache, osv_stub):
        """Batch tells us who is affected; only those get a second request."""
        osv_stub.vulnerable = {"flask": [vuln("GHSA-1")]}
        Scanner().scan(["flask==2.2.2", "clean-a==1.0", "clean-b==1.0"])
        assert osv_stub.batch_calls == 1
        assert osv_stub.package_calls == 1     # not 3

    def test_findings_sorted_by_severity(self, cache, osv_stub):
        osv_stub.vulnerable = {
            "low-pkg": [vuln("L", severity="LOW")],
            "crit-pkg": [vuln("C", severity="CRITICAL")],
            "mod-pkg": [vuln("M", severity="MODERATE")],
        }
        result = Scanner().scan(["low-pkg==1.0", "crit-pkg==1.0", "mod-pkg==1.0"])
        assert [f["package"] for f in result["findings"]] == ["crit-pkg", "mod-pkg", "low-pkg"]

    def test_duplicate_dependencies_scanned_once(self, cache, osv_stub):
        osv_stub.vulnerable = {"flask": [vuln("GHSA-1")]}
        result = Scanner().scan(["flask==2.2.2", "flask==2.2.2"])
        assert result["scanned"] == 1

    def test_unparseable_entries_are_reported_not_silently_dropped(self, cache, osv_stub):
        result = Scanner().scan(["flask==2.2.2", "-r requirements-dev.txt"])
        assert any("unrecognised" in w for w in result["warnings"])


class TestFailClosed:
    def test_upstream_failure_raises(self, cache, osv_stub):
        osv_stub.error = "connection refused"
        with pytest.raises(ScanError):
            Scanner().scan(["flask==2.2.2"])

    def test_upstream_failure_with_stale_cache_degrades_with_warning(self, cache, osv_stub):
        cache.seed({
            "_id": cache_key("flask", "2.2.2"),
            "package": "flask", "version": "2.2.2",
            "vulnerabilities": [vuln("GHSA-old")],
            "max_severity": "HIGH",
        }, age_seconds=99999)
        osv_stub.error = "connection refused"

        result = Scanner().scan(["flask==2.2.2"])

        assert result["findings"][0]["source"] == "cache-stale"
        assert any("stale" in w for w in result["warnings"])

    def test_partial_stale_cache_still_fails_closed(self, cache, osv_stub):
        """Half an answer is not an answer: do not silently drop the unknown half."""
        cache.seed({
            "_id": cache_key("flask", "2.2.2"),
            "package": "flask", "version": "2.2.2",
            "vulnerabilities": [vuln("GHSA-old")], "max_severity": "HIGH",
        }, age_seconds=99999)
        osv_stub.error = "connection refused"

        with pytest.raises(ScanError):
            Scanner().scan(["flask==2.2.2", "requests==2.28.1"])

    def test_cache_outage_falls_through_to_upstream(self, cache, osv_stub):
        cache.fail_on_read = True
        osv_stub.vulnerable = {"flask": [vuln("GHSA-1")]}

        result = Scanner().scan(["flask==2.2.2"])

        assert result["vulnerable"] == 1
        assert any("cache unavailable" in w for w in result["warnings"])


class TestCaching:
    def test_fresh_cache_avoids_upstream(self, cache, osv_stub):
        cache.seed({
            "_id": cache_key("flask", "2.2.2"),
            "package": "flask", "version": "2.2.2",
            "vulnerabilities": [vuln("GHSA-1")], "max_severity": "HIGH",
        }, age_seconds=10)

        result = Scanner().scan(["flask==2.2.2"])

        assert osv_stub.batch_calls == 0
        assert result["findings"][0]["source"] == "cache"

    def test_stale_cache_triggers_refetch(self, cache, osv_stub):
        cache.seed({
            "_id": cache_key("flask", "2.2.2"),
            "package": "flask", "version": "2.2.2",
            "vulnerabilities": [], "max_severity": "NONE",
        }, age_seconds=99999)
        osv_stub.vulnerable = {"flask": [vuln("GHSA-new")]}

        result = Scanner().scan(["flask==2.2.2"])

        assert osv_stub.batch_calls == 1
        assert result["findings"][0]["source"] == "osv"

    def test_results_are_written_back(self, cache, osv_stub):
        osv_stub.vulnerable = {"flask": [vuln("GHSA-1")]}
        Scanner().scan(["flask==2.2.2"])
        assert cache_key("flask", "2.2.2") in cache.store
