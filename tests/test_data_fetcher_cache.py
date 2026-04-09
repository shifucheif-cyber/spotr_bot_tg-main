import unittest
from datetime import datetime, timedelta, timezone

from services import data_fetcher


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
        self.assertIsNone(data_fetcher._get_cached("missing"))

    def test_put_cache_and_get_cached_round_trip(self):
        key = "cache-key"

        data_fetcher._put_cache(key, "payload")

        self.assertEqual(data_fetcher._get_cached(key), "payload")

    def test_get_cached_expires_old_entry(self):
        key = "expired-key"
        data_fetcher._match_cache[key] = {
            "result": "old-payload",
            "ts": datetime.now(tz=timezone.utc) - data_fetcher._CACHE_TTL - timedelta(seconds=1),
        }

        cached = data_fetcher._get_cached(key)

        self.assertIsNone(cached)
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

        data_fetcher._put_cache("fresh-key", "fresh-result")

        self.assertEqual(len(data_fetcher._match_cache), data_fetcher._CACHE_MAX)
        self.assertNotIn(oldest_key, data_fetcher._match_cache)
        self.assertEqual(data_fetcher._match_cache["fresh-key"]["result"], "fresh-result")


if __name__ == "__main__":
    unittest.main()