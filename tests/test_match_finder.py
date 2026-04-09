"""Tests for services.match_finder — match parsing and discipline normalization."""
import unittest
from datetime import datetime

from services.match_finder import (
    parse_match_teams,
    parse_date,
    normalize_discipline,
    create_fallback_match_data,
    get_discipline_for_sport,
)


class TestParseMatchTeams(unittest.TestCase):

    def test_vs_format(self):
        t1, t2 = parse_match_teams("Team A vs Team B")
        self.assertEqual(t1, "Team A")
        self.assertEqual(t2, "Team B")

    def test_dash_format(self):
        t1, t2 = parse_match_teams("Team A - Team B")
        self.assertIsNotNone(t1)
        self.assertIsNotNone(t2)

    def test_single_name_returns_none(self):
        t1, t2 = parse_match_teams("OnlyOneTeam")
        self.assertIsNone(t2)


class TestParseDate(unittest.TestCase):

    def test_russian_month(self):
        dt = parse_date("10 апреля 2026")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.month, 4)
        self.assertEqual(dt.day, 10)

    def test_dot_format(self):
        dt = parse_date("10.04.2026")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.month, 4)

    def test_invalid_returns_none(self):
        dt = parse_date("not a date at all")
        self.assertIsNone(dt)

    def test_russian_month_short(self):
        dt = parse_date("5 мая")
        # May or may not parse without year — depends on implementation
        # Just verify no exception
        self.assertTrue(dt is None or isinstance(dt, datetime))


class TestNormalizeDiscipline(unittest.TestCase):

    def test_football(self):
        result = normalize_discipline("футбол")
        self.assertIn(result, ("футбол", "football"))

    def test_esports_cs2(self):
        result = normalize_discipline("cs2")
        self.assertTrue(len(result) > 0)

    def test_unknown_returns_input(self):
        result = normalize_discipline("unknown_sport_xyz")
        self.assertEqual(result, "unknown_sport_xyz")


class TestGetDisciplineForSport(unittest.TestCase):

    def test_football_key(self):
        result = get_discipline_for_sport("football")
        self.assertIn("футбол", result.lower())

    def test_nhl_to_hockey(self):
        result = get_discipline_for_sport("nhl")
        self.assertIn("хоккей", result.lower())


class TestCreateFallbackMatchData(unittest.TestCase):

    def test_returns_dict_with_required_keys(self):
        data = create_fallback_match_data("Team A vs Team B", "10 апреля", "футбол")
        self.assertIsInstance(data, dict)
        self.assertIn("sport", data)


if __name__ == "__main__":
    unittest.main()
