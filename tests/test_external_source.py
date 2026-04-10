"""Tests for services.external_source — TheSportsDB integration."""
import asyncio
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

import httpx


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


if __name__ == "__main__":
    unittest.main()
