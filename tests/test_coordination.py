import time

import pytest

from coordination.ratelimit import LocalRateLimiter, RateLimitTimeout


class TestRateLimiter:
    def test_allows_up_to_the_budget(self):
        limiter = LocalRateLimiter(rate=5, window_seconds=30, wait_seconds=0)
        for _ in range(5):
            assert limiter.acquire() is True

    def test_blocks_once_the_budget_is_spent(self):
        limiter = LocalRateLimiter(rate=2, window_seconds=30, wait_seconds=0)
        limiter.acquire()
        limiter.acquire()
        with pytest.raises(RateLimitTimeout):
            limiter.acquire()

    def test_refills_over_time(self):
        # 20 per second: one token is back well within the wait window.
        limiter = LocalRateLimiter(rate=20, window_seconds=1, wait_seconds=2)
        for _ in range(20):
            limiter.acquire()
        start = time.monotonic()
        assert limiter.acquire() is True
        assert time.monotonic() - start < 2

    def test_does_not_bank_unlimited_tokens_while_idle(self):
        limiter = LocalRateLimiter(rate=3, window_seconds=0.1, wait_seconds=0)
        time.sleep(0.5)  # long idle - a naive refill would grant many tokens
        for _ in range(3):
            limiter.acquire()
        with pytest.raises(RateLimitTimeout):
            limiter.acquire()


class TestRefreshJob:
    def test_only_stale_entries_are_refreshed(self, cache, osv_stub):
        import refresh
        from scanner import cache_key

        cache.seed({"_id": cache_key("flask", "2.2.2"), "package": "flask",
                    "version": "2.2.2", "vulnerabilities": []}, age_seconds=99999)
        cache.seed({"_id": cache_key("requests", "2.28.1"), "package": "requests",
                    "version": "2.28.1", "vulnerabilities": []}, age_seconds=5)

        assert refresh.stale_specs() == [("flask", "2.2.2")]

    def test_refresh_ignores_cache_freshness_and_refetches(self, cache, osv_stub):
        import refresh
        from scanner import Scanner, cache_key

        cache.seed({"_id": cache_key("flask", "2.2.2"), "package": "flask",
                    "version": "2.2.2", "vulnerabilities": []}, age_seconds=99999)
        osv_stub.vulnerable = {"flask": [{"id": "GHSA-new", "severity": "HIGH",
                                         "cves": [], "fixed_in": []}]}

        count = refresh.refresh_once(Scanner())

        assert count == 1
        assert cache.store[cache_key("flask", "2.2.2")]["vulnerabilities"]

    def test_nothing_stale_is_a_no_op(self, cache, osv_stub):
        import refresh
        from scanner import Scanner

        assert refresh.refresh_once(Scanner()) == 0
        assert osv_stub.batch_calls == 0
