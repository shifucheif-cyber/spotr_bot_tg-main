"""Tests for sport-specific services — all 8 discipline wrappers."""
import asyncio
import unittest
from unittest.mock import patch, AsyncMock


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestBasketballService(unittest.TestCase):

    @patch("services.basketball_service.fetch_match_analysis_data", new_callable=AsyncMock, return_value="basketball data")
    def test_calls_fetcher(self, mock_fetch):
        from services.basketball_service import get_basketball_data
        result = run_async(get_basketball_data("Team A vs Team B"))
        mock_fetch.assert_called_once()
        self.assertEqual(result, "basketball data")


class TestFootballService(unittest.TestCase):

    @patch("services.football_service.fetch_match_analysis_data", new_callable=AsyncMock, return_value="football data")
    def test_calls_fetcher(self, mock_fetch):
        from services.football_service import get_football_data
        result = run_async(get_football_data("Team A vs Team B"))
        mock_fetch.assert_called_once()
        self.assertEqual(result, "football data")


class TestHockeyService(unittest.TestCase):

    @patch("services.hockey_service.fetch_match_analysis_data", new_callable=AsyncMock, return_value="hockey data")
    def test_calls_fetcher(self, mock_fetch):
        from services.hockey_service import get_hockey_data
        result = run_async(get_hockey_data("Team A vs Team B"))
        mock_fetch.assert_called_once()
        self.assertEqual(result, "hockey data")


class TestVolleyballService(unittest.TestCase):

    @patch("services.volleyball_service.fetch_match_analysis_data", new_callable=AsyncMock, return_value="volleyball data")
    def test_calls_fetcher(self, mock_fetch):
        from services.volleyball_service import get_volleyball_data
        result = run_async(get_volleyball_data("Team A vs Team B"))
        mock_fetch.assert_called_once()
        self.assertEqual(result, "volleyball data")


class TestTableTennisService(unittest.TestCase):

    @patch("services.table_tennis_service.fetch_match_analysis_data", new_callable=AsyncMock, return_value="tt data")
    def test_calls_fetcher(self, mock_fetch):
        from services.table_tennis_service import get_table_tennis_data
        result = run_async(get_table_tennis_data("A vs B"))
        mock_fetch.assert_called_once()
        self.assertEqual(result, "tt data")


class TestMMAService(unittest.TestCase):

    @patch("services.mma_service.fetch_match_analysis_data", new_callable=AsyncMock, return_value="mma data")
    def test_calls_fetcher(self, mock_fetch):
        from services.mma_service import get_mma_data
        result = run_async(get_mma_data("Fighter A vs Fighter B"))
        mock_fetch.assert_called_once()
        self.assertEqual(result, "mma data")

    @patch("services.mma_service.fetch_match_analysis_data", new_callable=AsyncMock, return_value="boxing data")
    def test_boxing_subdiscipline(self, mock_fetch):
        from services.mma_service import get_mma_data
        result = run_async(get_mma_data("Fighter A vs Fighter B", subdiscipline="boxing"))
        self.assertEqual(result, "boxing data")


class TestTennisService(unittest.TestCase):

    @patch("services.tennis_service.fetch_match_analysis_data", new_callable=AsyncMock, return_value="tennis data")
    def test_calls_fetcher(self, mock_fetch):
        from services.tennis_service import get_tennis_data
        result = run_async(get_tennis_data("Player A vs Player B"))
        mock_fetch.assert_called_once()
        self.assertEqual(result, "tennis data")

    @patch("services.table_tennis_service.get_table_tennis_data", new_callable=AsyncMock, return_value="tt delegated")
    def test_table_tennis_delegates(self, mock_tt):
        from services.tennis_service import get_tennis_data
        result = run_async(get_tennis_data("A vs B", subdiscipline="table_tennis"))
        mock_tt.assert_called_once()
        self.assertEqual(result, "tt delegated")


class TestCS2Service(unittest.TestCase):

    @patch("services.cs2_service.fetch_match_analysis_data", new_callable=AsyncMock, return_value="cs2 data")
    def test_cs2(self, mock_fetch):
        from services.cs2_service import get_esports_data
        result = run_async(get_esports_data("Team A vs Team B", "cs2"))
        mock_fetch.assert_called_once()
        self.assertEqual(result, "cs2 data")

    @patch("services.cs2_service.fetch_match_analysis_data", new_callable=AsyncMock, return_value="dota data")
    def test_dota2(self, mock_fetch):
        from services.cs2_service import get_esports_data
        result = run_async(get_esports_data("Team A vs Team B", "dota2"))
        mock_fetch.assert_called_once()
        self.assertEqual(result, "dota data")

    @patch("services.cs2_service.fetch_match_analysis_data", new_callable=AsyncMock, return_value="val data")
    def test_valorant(self, mock_fetch):
        from services.cs2_service import get_esports_data
        result = run_async(get_esports_data("Team A vs Team B", "valorant"))
        mock_fetch.assert_called_once()
        self.assertEqual(result, "val data")

    def test_unknown_discipline_returns_error_text(self):
        from services.cs2_service import get_esports_data
        result = run_async(get_esports_data("A vs B", "unknown_esport_xyz"))
        self.assertIn("неизвестная", result.lower())


if __name__ == "__main__":
    unittest.main()
