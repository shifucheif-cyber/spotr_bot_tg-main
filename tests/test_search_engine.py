import unittest
from unittest.mock import AsyncMock, patch

from services import search_engine


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
             patch.object(search_engine, "search_with_ddgs", return_value=ddg_results), \
             patch.object(search_engine, "search_with_serper", new=AsyncMock(return_value=[])) as mocked_serper, \
             patch.object(search_engine, "_fetch_page_excerpt", return_value=""):
            report = search_engine.collect_validated_sources(
                "Real Madrid",
                "football",
                "injuries lineup",
                min_sources=2,
                timelimit="m",
            )

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
             patch.object(search_engine, "search_with_ddgs", return_value=[]), \
             patch.object(search_engine, "search_with_serper", new=AsyncMock(return_value=serper_results)) as mocked_serper, \
             patch.object(search_engine, "_fetch_page_excerpt", return_value=""):
            report = search_engine.collect_validated_sources(
                "CSKA",
                "hockey",
                "roster recent results",
                min_sources=1,
                timelimit="m",
            )

        self.assertEqual(report["status"], "validated")
        self.assertEqual(report["validated_count"], 1)
        mocked_serper.assert_awaited()

    def test_validate_match_request_rejects_single_participant(self):
        report = search_engine.validate_match_request("Real Madrid", "10.04.26", "football")
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


if __name__ == "__main__":
    unittest.main()