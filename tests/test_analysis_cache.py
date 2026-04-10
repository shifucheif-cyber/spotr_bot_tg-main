"""Tests for services.analysis_cache — in-memory TTL cache for LLM results."""
import unittest
from datetime import datetime, timedelta, timezone

from services import analysis_cache


class AnalysisCacheTests(unittest.TestCase):
    def setUp(self):
        analysis_cache._analysis_cache.clear()

    def tearDown(self):
        analysis_cache._analysis_cache.clear()

    def test_cache_key_order_independent(self):
        k1 = analysis_cache.analysis_cache_key("football", "Real vs Barcelona", "2026-04-10")
        k2 = analysis_cache.analysis_cache_key("football", "Barcelona vs Real", "2026-04-10")
        self.assertEqual(k1, k2)

    def test_cache_key_date_sensitive(self):
        k1 = analysis_cache.analysis_cache_key("football", "A vs B", "2026-04-10")
        k2 = analysis_cache.analysis_cache_key("football", "A vs B", "2026-04-11")
        self.assertNotEqual(k1, k2)

    def test_cache_key_discipline_sensitive(self):
        k1 = analysis_cache.analysis_cache_key("football", "A vs B")
        k2 = analysis_cache.analysis_cache_key("hockey", "A vs B")
        self.assertNotEqual(k1, k2)

    def test_get_returns_none_for_missing(self):
        self.assertIsNone(analysis_cache.get_cached_analysis("missing"))

    def test_put_and_get_round_trip(self):
        result = {"provider": "groq", "text": "analysis text"}
        analysis_cache.put_cached_analysis("key1", result)
        self.assertEqual(analysis_cache.get_cached_analysis("key1"), result)

    def test_expired_entry_returns_none(self):
        analysis_cache._analysis_cache["old"] = {
            "result": {"provider": "groq", "text": "old"},
            "ts": datetime.now(tz=timezone.utc) - analysis_cache._CACHE_TTL - timedelta(seconds=1),
        }
        self.assertIsNone(analysis_cache.get_cached_analysis("old"))
        self.assertNotIn("old", analysis_cache._analysis_cache)

    def test_evicts_oldest_when_full(self):
        analysis_cache._analysis_cache["oldest"] = {
            "result": {"provider": "x", "text": "oldest"},
            "ts": datetime.now(tz=timezone.utc) - timedelta(hours=1),
        }
        for i in range(analysis_cache._CACHE_MAX - 1):
            analysis_cache._analysis_cache[f"k{i}"] = {
                "result": {"provider": "x", "text": f"v{i}"},
                "ts": datetime.now(tz=timezone.utc) + timedelta(seconds=i),
            }
        analysis_cache.put_cached_analysis("fresh", {"provider": "y", "text": "fresh"})
        self.assertEqual(len(analysis_cache._analysis_cache), analysis_cache._CACHE_MAX)
        self.assertNotIn("oldest", analysis_cache._analysis_cache)
        self.assertIn("fresh", analysis_cache._analysis_cache)

    def test_cache_key_with_protiv(self):
        """Handles Cyrillic 'против' separator."""
        k1 = analysis_cache.analysis_cache_key("хоккей", "Спартак против Динамо")
        k2 = analysis_cache.analysis_cache_key("хоккей", "Динамо против Спартак")
        self.assertEqual(k1, k2)


if __name__ == "__main__":
    unittest.main()
