import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from services import search_engine


def run_async(coro):
    """Helper to run async coroutine in sync test."""
    return asyncio.run(coro)


class SearchEngineTests(unittest.TestCase):
    def test_clean_context_terms_removes_placeholder_noise(self):
        cleaned = search_engine._clean_context_terms("User Query unknown Zenit vs CSKA")
        self.assertEqual(cleaned, "Zenit vs CSKA")

    def test_get_sites_for_query_prefers_global_sources_by_default(self):
        sites = search_engine._get_sites_for_query("football", "Real Madrid", "Barcelona La Liga")
        self.assertTrue(sites)
        self.assertEqual(sites[0], "whoscored.com")
        self.assertNotIn("premierliga.ru", sites)

    def test_get_sites_for_query_prioritizes_ru_sources_for_russian_context(self):
        sites = search_engine._get_sites_for_query("football", "Зенит", "ЦСКА РПЛ")
        self.assertTrue(sites)
        self.assertEqual(sites[0], "premierliga.ru")

    def test_collect_validated_sources_stops_after_ddg_when_enough(self):
        ddg_results = [
            {
                "title": "Real Madrid team news",
                "body": "Real Madrid lineup and injuries",
                "href": "https://whoscored.com/teams/52/show/spain-real-madrid",
                "search_engine": "ddg",
            },
            {
                "title": "Real Madrid player profile",
                "body": "Real Madrid ratings and squad",
                "href": "https://transfermarkt.com/real-madrid/startseite/verein/418",
                "search_engine": "ddg",
            },
        ]

        with patch.object(search_engine, "DDGS", object()), \
             patch.object(search_engine, "search_with_ddgs", new=AsyncMock(return_value=ddg_results)), \
             patch.object(search_engine, "search_with_serper", new=AsyncMock(return_value=[])) as mocked_serper, \
             patch.object(search_engine, "_fetch_page_excerpt_async", new=AsyncMock(return_value="")):
            report = run_async(search_engine.collect_validated_sources(
                "Real Madrid",
                "football",
                "injuries lineup",
                min_sources=2,
                timelimit="m",
            ))

        self.assertEqual(report["status"], "validated")
        self.assertEqual(report["validated_count"], 2)
        mocked_serper.assert_not_awaited()

    def test_collect_validated_sources_uses_serper_when_ddg_is_insufficient(self):
        serper_results = [
            {
                "title": "CSKA roster",
                "body": "CSKA current roster and recent results",
                "href": "https://flashscore.com/team/cska/123",
                "search_engine": "serper",
            }
        ]

        with patch.object(search_engine, "DDGS", object()), \
             patch.object(search_engine, "search_with_ddgs", new=AsyncMock(return_value=[])), \
             patch.object(search_engine, "search_with_serper", new=AsyncMock(return_value=serper_results)) as mocked_serper, \
             patch.object(search_engine, "_fetch_page_excerpt_async", new=AsyncMock(return_value="")):
            report = run_async(search_engine.collect_validated_sources(
                "CSKA",
                "hockey",
                "roster recent results",
                min_sources=1,
                timelimit="m",
            ))

        self.assertEqual(report["status"], "validated")
        self.assertEqual(report["validated_count"], 1)
        mocked_serper.assert_awaited()

    def test_validate_match_request_rejects_single_participant(self):
        report = run_async(search_engine.validate_match_request("Real Madrid", "10.04.26", "football"))
        self.assertEqual(report["status"], "insufficient_sources")
        self.assertIsNone(report["match"])


class CheckRequiredDataTests(unittest.TestCase):
    def test_all_found(self):
        text = "форма последние 5 матчей очные встречи H2H травмы дисквалификации"
        result = search_engine.check_required_data(text, ["form", "h2h", "injuries"], "football")
        self.assertTrue(result["satisfied"])
        self.assertEqual(result["missing"], [])

    def test_none_found(self):
        text = "Какой-то нерелевантный текст без данных"
        result = search_engine.check_required_data(text, ["form", "h2h", "injuries"], "football")
        self.assertFalse(result["satisfied"])
        self.assertEqual(sorted(result["missing"]), ["form", "h2h", "injuries"])

    def test_partial(self):
        text = "Форма команды за последние 5 матчей: ВВНПВ"
        result = search_engine.check_required_data(text, ["form", "h2h", "injuries"], "football")
        self.assertFalse(result["satisfied"])
        self.assertIn("form", result["found"])
        self.assertIn("h2h", result["missing"])

    def test_empty_text(self):
        result = search_engine.check_required_data("", ["form"], "football")
        self.assertFalse(result["satisfied"])
        self.assertEqual(result["missing"], ["form"])

    def test_empty_keys(self):
        result = search_engine.check_required_data("some text", [], "football")
        self.assertTrue(result["satisfied"])

    def test_case_insensitive(self):
        text = "HEAD TO HEAD statistics H2H INJURIES suspended"
        result = search_engine.check_required_data(text, ["h2h", "injuries"], "football")
        self.assertTrue(result["satisfied"])


class TestSerperBackoff(unittest.TestCase):
    """Exponential backoff on 429 for search_with_serper."""

    @patch("services.search_providers.providers.SERPER_API_KEY", "fake-key")
    @patch("services.search_providers.providers.asyncio.sleep", new_callable=AsyncMock)
    @patch("services.search_providers.providers.httpx.AsyncClient")
    def test_retries_on_429_with_exponential_delay(self, mock_client_cls, mock_sleep):
        from services.search_providers.providers import search_with_serper

        mock_resp_429 = MagicMock()
        mock_resp_429.status_code = 429
        mock_resp_429.raise_for_status.side_effect = httpx.HTTPStatusError(
            "429", request=MagicMock(), response=mock_resp_429
        )

        mock_resp_ok = MagicMock()
        mock_resp_ok.status_code = 200
        mock_resp_ok.raise_for_status = MagicMock()
        mock_resp_ok.json.return_value = {"organic": [{"title": "T", "snippet": "S", "link": "https://x.com"}]}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[mock_resp_429, mock_resp_ok])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = run_async(search_with_serper("test query"))
        self.assertEqual(len(result), 1)
        mock_sleep.assert_awaited_once_with(1)  # 2^0 = 1


if __name__ == "__main__":
    unittest.main()