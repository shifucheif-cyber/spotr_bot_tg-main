"""Tests for services.name_normalizer — entity name normalization and matching."""
import unittest

from services.name_normalizer import (
    split_match_text,
    transliterate_text,
    normalize_entity_name,
    get_search_variants,
    resolve_match_entities,
)


class TestSplitMatchText(unittest.TestCase):

    def test_vs_separator(self):
        self.assertEqual(split_match_text("Team A vs Team B"), ["Team A", "Team B"])

    def test_vs_dot_separator(self):
        self.assertEqual(split_match_text("Team A vs. Team B"), ["Team A", "Team B"])

    def test_dash_separator(self):
        parts = split_match_text("Team A - Team B")
        self.assertEqual(len(parts), 2)

    def test_single_name_returns_list(self):
        parts = split_match_text("OnlyOneTeam")
        self.assertEqual(len(parts), 1)

    def test_protiv_separator(self):
        parts = split_match_text("Команда А против Команда Б")
        self.assertEqual(len(parts), 2)


class TestTransliterateText(unittest.TestCase):

    def test_cyrillic_to_latin(self):
        result = transliterate_text("спартак")
        self.assertTrue(result.isascii())
        self.assertIn("spartak", result)

    def test_already_latin_unchanged(self):
        self.assertEqual(transliterate_text("manchester"), "manchester")

    def test_empty_string(self):
        self.assertEqual(transliterate_text(""), "")


class TestNormalizeEntityName(unittest.TestCase):

    def test_strips_fc_prefix(self):
        result = normalize_entity_name("FC Spartak")
        self.assertNotIn("fc", result.split())

    def test_lowercase(self):
        result = normalize_entity_name("CSKA Moscow")
        self.assertEqual(result, result.lower())

    def test_strips_extra_spaces(self):
        result = normalize_entity_name("  Team   Name  ")
        self.assertNotIn("  ", result)


class TestGetSearchVariants(unittest.TestCase):

    def test_returns_nonempty(self):
        variants = get_search_variants("Реал Мадрид", discipline="футбол")
        self.assertTrue(len(variants) > 0)

    def test_limit_respected(self):
        variants = get_search_variants("Manchester United", limit=2)
        self.assertLessEqual(len(variants), 2)


class TestResolveMatchEntities(unittest.TestCase):

    def test_returns_dict_with_keys(self):
        result = resolve_match_entities("Реал", "Барселона", discipline="футбол")
        self.assertIn("team1", result)
        self.assertIn("team2", result)


if __name__ == "__main__":
    unittest.main()
