import unittest

from services.betting_calculator import (
    calculate_value_bet,
    extract_betting_data,
    extract_probability,
    get_bet_recommendation,
    normalize_score,
)


class BettingCalculatorTests(unittest.TestCase):
    def test_normalize_score_supports_multiple_separators(self):
        self.assertEqual(normalize_score("2:1"), "2:1")
        self.assertEqual(normalize_score("2-1"), "2:1")
        self.assertEqual(normalize_score("2 1"), "2:1")
        self.assertEqual(normalize_score(None), "Н/Д")

    def test_extract_probability_from_contract_markdown(self):
        response = "📈 **Вероятность победы (1-я сторона):** 58%"
        self.assertEqual(extract_probability(response), 58.0)

    def test_extract_probability_from_plain_text(self):
        response = "Вероятность победы (1-я сторона): 61,5%"
        self.assertEqual(extract_probability(response), 61.5)

    def test_extract_probability_from_short_p_marker(self):
        response = "P=54%"
        self.assertEqual(extract_probability(response), 54.0)

    def test_extract_probability_ignores_out_of_range_values(self):
        response = "📈 **Вероятность победы (1-я сторона):** 120%"
        self.assertIsNone(extract_probability(response))

    def test_extract_probability_returns_none_for_template_placeholder(self):
        response = "📈 **Вероятность победы (1-я сторона):** P%"
        self.assertIsNone(extract_probability(response))

    def test_extract_betting_data_prefers_json_fields(self):
        response = '''```json
        {
          "win_probability_team1": 62,
          "win_probability_team2": 38,
          "odds": 1.95,
          "recommended_bet_size": 3,
          "analysis_summary": "Команда 1 в лучшей форме",
          "exact_score": "2-1",
          "total_prediction": "2.5",
          "total_recommendation": "ТБ 2.5"
        }
        ```'''

        data = extract_betting_data(response)

        self.assertEqual(data["probability"], 62.0)
        self.assertEqual(data["win_probability_team1"], 62.0)
        self.assertEqual(data["win_probability_team2"], 38.0)
        self.assertEqual(data["odds"], 1.95)
        self.assertEqual(data["recommended_bet_size"], 3)
        self.assertEqual(data["exact_score"], "2:1")
        self.assertEqual(data["total_prediction"], 2.5)
        self.assertEqual(data["total_recommendation"], "ТБ 2.5")

    def test_extract_betting_data_falls_back_to_regex_probability(self):
        response = "Анализ матча\nВероятность победы: 57%"

        data = extract_betting_data(response)

        self.assertEqual(data["probability"], 57.0)
        self.assertEqual(data["win_probability_team1"], 57.0)
        self.assertIsNone(data["win_probability_team2"])

    def test_calculate_value_bet_returns_skip_for_invalid_probability(self):
        result = calculate_value_bet(100)
        self.assertEqual(result["stake_percent"], "ПРОПУСК")
        self.assertIn("недопустимо", result["recommendation"])

    def test_calculate_value_bet_without_odds_returns_threshold_hint(self):
        result = calculate_value_bet(55)
        self.assertIn("Ищите коэффициент строго >", result["recommendation"])
        self.assertIn("ПРИ кэфе >", result["stake_percent"])

    def test_get_bet_recommendation_handles_placeholder_probability(self):
        response = "Вероятность победы: P%"

        result = get_bet_recommendation(response)

        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["stake_percent"], "ПРОПУСК")
        self.assertIn("P%", result["recommendation"])

    def test_get_bet_recommendation_uses_json_recommended_bet_size(self):
        response = '''```json
        {
          "probability": 64,
          "recommended_bet_size": 4,
          "odds": 2.1
        }
        ```'''

        result = get_bet_recommendation(response)

        self.assertEqual(result["probability"], 64.0)
        self.assertEqual(result["stake_percent"], "4.0%")
        self.assertEqual(result["status"], "success")


    # --- Total fallback tests ---

    def test_total_fallback_from_exact_score(self):
        response = '```json\n{"win_probability_team1": 60, "exact_score": "2:0"}\n```'
        data = extract_betting_data(response)
        self.assertEqual(data["total_prediction"], 1.5)
        self.assertEqual(data["total_recommendation"], "ТБ 1.5")
        self.assertEqual(data["total_value"], "1.5")

    def test_total_fallback_basketball(self):
        response = '```json\n{"win_probability_team1": 55, "exact_score": "105:98"}\n```'
        data = extract_betting_data(response)
        self.assertEqual(data["total_prediction"], 202.5)

    def test_total_fallback_does_not_overwrite_llm(self):
        response = '```json\n{"win_probability_team1": 60, "exact_score": "2:1", "total_prediction": 3.5}\n```'
        data = extract_betting_data(response)
        self.assertEqual(data["total_prediction"], 3.5)

    # --- Simple stake tests ---

    def test_simple_stake_high_probability(self):
        response = '```json\n{"win_probability_team1": 85, "win_probability_team2": 15, "odds": 1.5}\n```'
        result = get_bet_recommendation(response)
        self.assertEqual(result["simple_stake"], "6%")

    def test_simple_stake_medium_probability(self):
        response = '```json\n{"win_probability_team1": 70, "win_probability_team2": 30, "odds": 1.8}\n```'
        result = get_bet_recommendation(response)
        self.assertEqual(result["simple_stake"], "3%")

    def test_simple_stake_low_probability(self):
        response = '```json\n{"win_probability_team1": 55, "win_probability_team2": 45, "odds": 2.0}\n```'
        result = get_bet_recommendation(response)
        self.assertEqual(result["simple_stake"], "1%")


if __name__ == "__main__":
    unittest.main()