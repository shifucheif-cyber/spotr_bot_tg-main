import asyncio
import unittest
from datetime import datetime, timedelta, timezone

from services import data_fetcher
from services.event_phase import EventPhase


def run_async(coro):
    return asyncio.run(coro)


class DataFetcherCacheTests(unittest.TestCase):
    def setUp(self):
        data_fetcher._match_cache.clear()

    def tearDown(self):
        data_fetcher._match_cache.clear()

    def test_cache_key_is_order_independent_and_date_sensitive(self):
        key1 = data_fetcher._cache_key("football", "Team A", "Team B", "2026-04-10")
        key2 = data_fetcher._cache_key("football", "team b", "team a", "2026-04-10")
        key3 = data_fetcher._cache_key("football", "Team A", "Team B", "2026-04-11")

        self.assertEqual(key1, key2)
        self.assertNotEqual(key1, key3)

    def test_get_cached_returns_none_for_missing_key(self):
        self.assertIsNone(run_async(data_fetcher._get_cached("missing")))

    def test_put_cache_and_get_cached_round_trip(self):
        key = "cache-key"
        run_async(data_fetcher._put_cache(key, "payload"))
        self.assertEqual(run_async(data_fetcher._get_cached(key)), "payload")

    def test_get_cached_expires_old_entry(self):
        key = "expired-key"
        data_fetcher._match_cache[key] = {
            "result": "old-payload",
            "ts": datetime.now(tz=timezone.utc) - data_fetcher._DEFAULT_SEARCH_TTL - timedelta(seconds=1),
        }
        self.assertIsNone(run_async(data_fetcher._get_cached(key)))
        self.assertNotIn(key, data_fetcher._match_cache)

    def test_put_cache_evicts_oldest_when_capacity_reached(self):
        oldest_key = "oldest"
        data_fetcher._match_cache[oldest_key] = {
            "result": "oldest-result",
            "ts": datetime.now(tz=timezone.utc) - timedelta(days=1),
        }
        for idx in range(data_fetcher._CACHE_MAX - 1):
            data_fetcher._match_cache[f"key-{idx}"] = {
                "result": f"value-{idx}",
                "ts": datetime.now(tz=timezone.utc) + timedelta(seconds=idx),
            }
        run_async(data_fetcher._put_cache("fresh-key", "fresh-result"))
        self.assertEqual(len(data_fetcher._match_cache), data_fetcher._CACHE_MAX)
        self.assertNotIn(oldest_key, data_fetcher._match_cache)
        self.assertEqual(data_fetcher._match_cache["fresh-key"]["result"], "fresh-result")

    # --- Phase-based TTL ---

    def test_phase_early_uses_7d_ttl(self):
        run_async(data_fetcher._put_cache("early_k", "data"))
        # Move timestamp back 6d — should still be valid with EARLY (7d TTL)
        data_fetcher._match_cache["early_k"]["ts"] = datetime.now(tz=timezone.utc) - timedelta(days=6)
        self.assertEqual(run_async(data_fetcher._get_cached("early_k", phase=EventPhase.EARLY)), "data")

    def test_phase_live_always_fresh(self):
        run_async(data_fetcher._put_cache("live_k", "data"))
        data_fetcher._match_cache["live_k"]["ts"] = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
        self.assertIsNone(run_async(data_fetcher._get_cached("live_k", phase=EventPhase.LIVE)))

    def test_phase_finished_uses_48h_ttl(self):
        run_async(data_fetcher._put_cache("fin_k", "data"))
        data_fetcher._match_cache["fin_k"]["ts"] = datetime.now(tz=timezone.utc) - timedelta(hours=47)
        self.assertEqual(run_async(data_fetcher._get_cached("fin_k", phase=EventPhase.FINISHED)), "data")

    # --- Cleanup ---

    def test_cleanup_expired_cache(self):
        run_async(data_fetcher._put_cache("fresh", "data"))
        data_fetcher._match_cache["old"] = {
            "result": "old-data",
            "ts": datetime.now(tz=timezone.utc) - timedelta(hours=49),
        }
        removed = run_async(data_fetcher.cleanup_expired_cache())
        self.assertEqual(removed, 1)
        self.assertIn("fresh", data_fetcher._match_cache)
        self.assertNotIn("old", data_fetcher._match_cache)


if __name__ == "__main__":
    unittest.main()