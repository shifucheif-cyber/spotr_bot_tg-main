"""Tests for services.external_source — TheSportsDB integration."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock, MagicMock

import httpx
from services import external_source


def run_async(coro):
    return asyncio.run(coro)


class TestSearchEventTheSportsDB(unittest.TestCase):

    def _mock_async_client(self, response_json=None, raise_for_status=None, side_effect=None):
        """Create a mock for httpx.AsyncClient context manager."""
        mock_resp = MagicMock()
        if response_json is not None:
            mock_resp.json.return_value = response_json
        if raise_for_status:
            mock_resp.raise_for_status.side_effect = raise_for_status
        else:
            mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        if side_effect:
            mock_client.get.side_effect = side_effect
        else:
            mock_client.get.return_value = mock_resp

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_client
        mock_cm.__aexit__.return_value = False
        return mock_cm

    @patch("services.external_source.httpx.AsyncClient")
    def test_found_event(self, MockAsyncClient):
        mock_cm = self._mock_async_client(
            response_json={"event": [{"strEvent": "Team A vs Team B", "strHomeTeam": "Team A", "strAwayTeam": "Team B"}]}
        )
        MockAsyncClient.return_value = mock_cm

        from services.external_source import search_event_thesportsdb
        result = run_async(search_event_thesportsdb("Team A vs Team B"))
        self.assertIsNotNone(result)
        self.assertEqual(result["strHomeTeam"], "Team A")

    @patch("services.external_source.httpx.AsyncClient")
    def test_no_events(self, MockAsyncClient):
        mock_cm = self._mock_async_client(response_json={"event": None})
        MockAsyncClient.return_value = mock_cm

        from services.external_source import search_event_thesportsdb
        result = run_async(search_event_thesportsdb("Nonexistent Match"))
        self.assertIsNone(result)

    @patch("services.external_source.httpx.AsyncClient")
    def test_connection_error(self, MockAsyncClient):
        mock_cm = self._mock_async_client(side_effect=httpx.ConnectError("connection refused"))
        MockAsyncClient.return_value = mock_cm

        from services.external_source import search_event_thesportsdb
        result = run_async(search_event_thesportsdb("Team A vs Team B"))
        self.assertIsNone(result)

    @patch("services.external_source.httpx.AsyncClient")
    def test_timeout(self, MockAsyncClient):
        mock_cm = self._mock_async_client(side_effect=httpx.TimeoutException("timeout"))
        MockAsyncClient.return_value = mock_cm

        from services.external_source import search_event_thesportsdb
        result = run_async(search_event_thesportsdb("Team A vs Team B"))
        self.assertIsNone(result)

    @patch("services.external_source.httpx.AsyncClient")
    def test_http_error(self, MockAsyncClient):
        mock_cm = self._mock_async_client(
            raise_for_status=httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock())
        )
        MockAsyncClient.return_value = mock_cm

        from services.external_source import search_event_thesportsdb
        result = run_async(search_event_thesportsdb("Team A vs Team B"))
        self.assertIsNone(result)


class TestTeamIdCache(unittest.TestCase):
    def setUp(self):
        external_source._team_id_cache.clear()

    def tearDown(self):
        external_source._team_id_cache.clear()

    @patch("services.external_source.httpx.AsyncClient")
    def test_cache_hit_no_http(self, MockAsyncClient):
        """Second call should use cache, not HTTP."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"teams": [{"idTeam": "12345"}]}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_client
        mock_cm.__aexit__.return_value = False
        MockAsyncClient.return_value = mock_cm

        result1 = run_async(external_source._search_team_id("Manchester United"))
        self.assertEqual(result1, "12345")
        self.assertEqual(mock_client.get.call_count, 1)

        # Second call — cache hit
        result2 = run_async(external_source._search_team_id("Manchester United"))
        self.assertEqual(result2, "12345")
        self.assertEqual(mock_client.get.call_count, 1)  # no new HTTP call

    @patch("services.external_source.httpx.AsyncClient")
    def test_none_not_cached(self, MockAsyncClient):
        """None results should not be cached."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"teams": None}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_client
        mock_cm.__aexit__.return_value = False
        MockAsyncClient.return_value = mock_cm

        result = run_async(external_source._search_team_id("Nonexistent Team"))
        self.assertIsNone(result)
        self.assertEqual(len(external_source._team_id_cache), 0)

    def test_cleanup_team_cache(self):
        external_source._team_id_cache["old"] = {
            "result": "123",
            "ts": datetime.now(tz=timezone.utc) - timedelta(hours=49),
        }
        external_source._team_id_cache["fresh"] = {
            "result": "456",
            "ts": datetime.now(tz=timezone.utc),
        }
        removed = external_source.cleanup_team_cache()
        self.assertEqual(removed, 1)
        self.assertNotIn("old", external_source._team_id_cache)
        self.assertIn("fresh", external_source._team_id_cache)


if __name__ == "__main__":
    unittest.main()
