"""Tests for services.external_source — TheSportsDB integration."""
import unittest
from unittest.mock import patch, MagicMock

import httpx


class TestSearchEventTheSportsDB(unittest.TestCase):

    @patch("services.external_source.httpx.get")
    def test_found_event(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "event": [{"strEvent": "Team A vs Team B", "strHomeTeam": "Team A", "strAwayTeam": "Team B"}]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from services.external_source import search_event_thesportsdb
        result = search_event_thesportsdb("Team A vs Team B")
        self.assertIsNotNone(result)
        self.assertEqual(result["strHomeTeam"], "Team A")

    @patch("services.external_source.httpx.get")
    def test_no_events(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"event": None}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from services.external_source import search_event_thesportsdb
        result = search_event_thesportsdb("Nonexistent Match")
        self.assertIsNone(result)

    @patch("services.external_source.httpx.get", side_effect=httpx.ConnectError("connection refused"))
    def test_connection_error(self, mock_get):
        from services.external_source import search_event_thesportsdb
        result = search_event_thesportsdb("Team A vs Team B")
        self.assertIsNone(result)

    @patch("services.external_source.httpx.get", side_effect=httpx.TimeoutException("timeout"))
    def test_timeout(self, mock_get):
        from services.external_source import search_event_thesportsdb
        result = search_event_thesportsdb("Team A vs Team B")
        self.assertIsNone(result)

    @patch("services.external_source.httpx.get")
    def test_http_error(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock()
        )
        mock_get.return_value = mock_resp

        from services.external_source import search_event_thesportsdb
        result = search_event_thesportsdb("Team A vs Team B")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
