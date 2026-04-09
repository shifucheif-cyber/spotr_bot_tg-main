"""Tests for services.discipline_config."""

import unittest
from services.discipline_config import (
    DISCIPLINE_CONFIG,
    get_config,
    get_search_queries,
    get_h2h_query,
    _current_season,
)


class TestDisciplineConfig(unittest.TestCase):

    def test_all_12_disciplines_present(self):
        expected = {
            "football", "hockey", "basketball", "volleyball",
            "tennis", "table_tennis", "mma", "boxing",
            "cs2", "dota2", "lol", "valorant",
        }
        self.assertEqual(set(DISCIPLINE_CONFIG.keys()), expected)

    def test_get_config_existing(self):
        cfg = get_config("football")
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg["participant_type"], "team")

    def test_get_config_missing(self):
        self.assertIsNone(get_config("curling"))

    def test_required_keys_in_every_config(self):
        required = {
            "participant_type", "has_total", "has_draw",
            "search_templates_ru", "search_templates_en",
            "h2h_template_ru", "h2h_template_en",
            "required_data", "desired_data",
        }
        for disc, cfg in DISCIPLINE_CONFIG.items():
            for key in required:
                self.assertIn(key, cfg, f"{disc} missing key '{key}'")

    def test_search_templates_have_entity_placeholder(self):
        for disc, cfg in DISCIPLINE_CONFIG.items():
            for tpl in cfg["search_templates_ru"] + cfg["search_templates_en"]:
                self.assertIn("{entity}", tpl, f"{disc}: template missing {{entity}}: {tpl}")

    def test_get_search_queries_returns_list(self):
        cfg = get_config("tennis")
        queries = get_search_queries(cfg, "Medvedev", "tennis", is_russian=False)
        self.assertIsInstance(queries, list)
        self.assertTrue(len(queries) >= 2)
        self.assertIn("Medvedev", queries[0])

    def test_get_search_queries_russian(self):
        cfg = get_config("football")
        queries = get_search_queries(cfg, "Зенит", "football", is_russian=True)
        self.assertTrue(any("футбол" in q for q in queries))

    def test_get_h2h_query(self):
        cfg = get_config("cs2")
        q = get_h2h_query(cfg, "NaVi", "Spirit", "cs2", is_russian=False)
        self.assertIn("NaVi", q)
        self.assertIn("Spirit", q)

    def test_current_season_format(self):
        season = _current_season()
        self.assertRegex(season, r"\d{4}/\d{4}")


class TestParticipantTypes(unittest.TestCase):

    def test_team_sports(self):
        for disc in ("football", "hockey", "basketball", "volleyball", "cs2", "dota2", "lol", "valorant"):
            self.assertEqual(DISCIPLINE_CONFIG[disc]["participant_type"], "team", disc)

    def test_solo_sports(self):
        for disc in ("mma", "boxing"):
            self.assertEqual(DISCIPLINE_CONFIG[disc]["participant_type"], "solo", disc)

    def test_solo_or_pair(self):
        for disc in ("tennis", "table_tennis"):
            self.assertEqual(DISCIPLINE_CONFIG[disc]["participant_type"], "solo_or_pair", disc)


if __name__ == "__main__":
    unittest.main()
