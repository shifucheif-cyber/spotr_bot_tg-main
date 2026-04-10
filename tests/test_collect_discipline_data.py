"""Tests for collect_discipline_data (new pipeline)."""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch, MagicMock


class TestCollectDisciplineData(unittest.TestCase):

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    @patch("services.search_engine.SERPER_API_KEY", "test-key")
    @patch("services.search_engine.search_with_serper", new_callable=AsyncMock)
    @patch("services.search_engine._fetch_page_excerpt_async", new_callable=AsyncMock)
    def test_serper_primary(self, mock_excerpt, mock_serper):
        """If Serper returns results, Tavily/DDG are NOT called."""
        call_count = [0]
        async def make_result(*args, **kwargs):
            call_count[0] += 1
            return [
                {"title": f"Result {call_count[0]}", "body": "snippet", "href": f"https://example.com/{call_count[0]}", "search_engine": "serper"},
            ]
        mock_serper.side_effect = make_result
        mock_excerpt.return_value = "page text"

        from services.search_engine import collect_discipline_data
        result = self._run(collect_discipline_data(
            ["Team A", "Team B"], "football",
        ))
        self.assertIn("TEAM A", result)
        self.assertIn("TEAM B", result)
        # 2 queries per participant + 1 h2h = 5 calls
        self.assertEqual(mock_serper.call_count, 5)

    @patch("services.search_engine.SERPER_API_KEY", None)
    @patch("services.search_engine.TAVILY_API_KEY", None)
    @patch("services.search_engine.EXA_API_KEY", None)
    @patch("services.search_engine.DDGS", None)
    @patch("services.search_engine._fetch_page_excerpt_async", new_callable=AsyncMock)
    def test_no_engines_available(self, mock_excerpt):
        """No engines available — returns report with 0 sources."""
        mock_excerpt.return_value = ""
        from services.search_engine import collect_discipline_data
        result = self._run(collect_discipline_data(
            ["Team A", "Team B"], "football",
        ))
        self.assertIn("Источников: 0", result)

    @patch("services.search_engine.SERPER_API_KEY", None)
    @patch("services.search_engine.search_with_ddgs", new_callable=AsyncMock)
    @patch("services.search_engine._fetch_page_excerpt_async", new_callable=AsyncMock)
    @patch("services.search_engine._merge_analysis_results", new_callable=AsyncMock)
    def test_fallback_to_ddg(self, mock_merge, mock_excerpt, mock_ddg):
        """Serper unavailable, Tavily empty → falls through to DDG."""
        mock_merge.return_value = {"results": [], "answers": []}
        mock_ddg.return_value = [
            {"title": "DDG Result", "body": "ddg snippet", "href": "https://ddg.example.com", "search_engine": "ddg"},
        ]
        mock_excerpt.return_value = ""

        from services.search_engine import collect_discipline_data
        result = self._run(collect_discipline_data(
            ["Fighter A", "Fighter B"], "mma",
        ))
        self.assertIn("DDG Result", result)

    def test_unsupported_discipline(self):
        from services.search_engine import collect_discipline_data
        result = self._run(collect_discipline_data(["A", "B"], "curling"))
        self.assertIn("не поддерживается", result)


class TestFetchPageExcerptAsync(unittest.TestCase):

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    @patch("services.search_engine.httpx.AsyncClient")
    def test_extracts_text(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.text = "<html><body><p>Hello World Team A stats</p></body></html>"
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        from services.search_engine import _fetch_page_excerpt_async
        result = self._run(_fetch_page_excerpt_async("https://example.com", "Team A"))
        self.assertIn("Team A", result)

    def test_empty_url(self):
        from services.search_engine import _fetch_page_excerpt_async
        result = self._run(_fetch_page_excerpt_async("", "test"))
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
