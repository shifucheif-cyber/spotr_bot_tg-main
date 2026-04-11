"""Tests for services.analysis_cache — in-memory TTL cache for LLM results."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone

from services import analysis_cache
from services.event_phase import EventPhase


def run_async(coro):
    return asyncio.run(coro)


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
        self.assertIsNone(run_async(analysis_cache.get_cached_analysis("missing")))

    def test_put_and_get_round_trip(self):
        result = {"provider": "groq", "text": "analysis text"}
        run_async(analysis_cache.put_cached_analysis("key1", result))
        self.assertEqual(run_async(analysis_cache.get_cached_analysis("key1")), result)

    def test_expired_entry_returns_none(self):
        analysis_cache._analysis_cache["old"] = {
            "result": {"provider": "groq", "text": "old"},
            "ts": datetime.now(tz=timezone.utc) - analysis_cache._DEFAULT_LLM_TTL - timedelta(seconds=1),
        }
        self.assertIsNone(run_async(analysis_cache.get_cached_analysis("old")))
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
        run_async(analysis_cache.put_cached_analysis("fresh", {"provider": "y", "text": "fresh"}))
        self.assertEqual(len(analysis_cache._analysis_cache), analysis_cache._CACHE_MAX)
        self.assertNotIn("oldest", analysis_cache._analysis_cache)
        self.assertIn("fresh", analysis_cache._analysis_cache)

    def test_cache_key_with_protiv(self):
        """Handles Cyrillic 'против' separator."""
        k1 = analysis_cache.analysis_cache_key("хоккей", "Спартак против Динамо")
        k2 = analysis_cache.analysis_cache_key("хоккей", "Динамо против Спартак")
        self.assertEqual(k1, k2)

    # --- Phase-based TTL tests ---

    def test_phase_early_uses_7d_ttl(self):
        """EARLY phase: entry at 6d ago should still be valid (TTL=7d)."""
        result = {"provider": "groq", "text": "early"}
        analysis_cache._analysis_cache["phase_key"] = {
            "result": result,
            "ts": datetime.now(tz=timezone.utc) - timedelta(days=6),
        }
        self.assertEqual(run_async(analysis_cache.get_cached_analysis("phase_key", phase=EventPhase.EARLY)), result)

    def test_phase_live_always_fresh(self):
        """LIVE phase: TTL=0, any cached entry is expired."""
        analysis_cache._analysis_cache["live_key"] = {
            "result": {"provider": "groq", "text": "live"},
            "ts": datetime.now(tz=timezone.utc) - timedelta(seconds=1),
        }
        self.assertIsNone(run_async(analysis_cache.get_cached_analysis("live_key", phase=EventPhase.LIVE)))

    def test_phase_finished_uses_48h_ttl(self):
        """FINISHED phase: entry at 47h ago should be valid (TTL=48h)."""
        result = {"provider": "groq", "text": "finished"}
        analysis_cache._analysis_cache["fin_key"] = {
            "result": result,
            "ts": datetime.now(tz=timezone.utc) - timedelta(hours=47),
        }
        self.assertEqual(run_async(analysis_cache.get_cached_analysis("fin_key", phase=EventPhase.FINISHED)), result)

    def test_phase_finished_expired_49h(self):
        """FINISHED phase: entry at 49h ago should be expired (TTL=48h)."""
        analysis_cache._analysis_cache["fin_old"] = {
            "result": {"provider": "groq", "text": "old"},
            "ts": datetime.now(tz=timezone.utc) - timedelta(hours=49),
        }
        self.assertIsNone(run_async(analysis_cache.get_cached_analysis("fin_old", phase=EventPhase.FINISHED)))

    def test_phase_none_uses_default_ttl(self):
        """No phase: uses default 2h TTL."""
        result = {"provider": "groq", "text": "default"}
        analysis_cache._analysis_cache["def_key"] = {
            "result": result,
            "ts": datetime.now(tz=timezone.utc) - timedelta(hours=1, minutes=59),
        }
        self.assertEqual(run_async(analysis_cache.get_cached_analysis("def_key")), result)

    # --- Cleanup test ---

    def test_cleanup_expired_cache(self):
        analysis_cache._analysis_cache["fresh"] = {
            "result": {"text": "fresh"},
            "ts": datetime.now(tz=timezone.utc),
        }
        analysis_cache._analysis_cache["old"] = {
            "result": {"text": "old"},
            "ts": datetime.now(tz=timezone.utc) - timedelta(hours=49),
        }
        removed = run_async(analysis_cache.cleanup_expired_cache())
        self.assertEqual(removed, 1)
        self.assertIn("fresh", analysis_cache._analysis_cache)
        self.assertNotIn("old", analysis_cache._analysis_cache)


if __name__ == "__main__":
    unittest.main()
