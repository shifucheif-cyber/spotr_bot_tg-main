import unittest

from services.response_formatter import (
    format_prediction_response,
    format_response_contract,
    split_long_message,
    validate_prediction_consistency,
)


class ResponseFormatterTests(unittest.TestCase):
    def test_validate_prediction_consistency_flips_score_for_second_team_winner(self):
        prediction = {
            "winner": "CSKA",
            "win_probability_team1": 58,
            "exact_score": "2:1",
        }

        validate_prediction_consistency(prediction, team1="SKA", team2="CSKA")

        self.assertEqual(prediction["exact_score"], "1:2")

    def test_format_response_contract_normalizes_probability_sum(self):
        prediction = {
            "winner": "Real Madrid",
            "win_probability_team1": 70,
            "win_probability_team2": 20,
            "exact_score": "2:1",
            "total_prediction": 2.5,
            "total_recommendation": "ТБ 2.5",
            "stake_percent": "3%",
            "analysis_summary": "Real Madrid stronger in recent form.",
            "recommendation": "Ставка на победу первой команды",
        }

        html = format_response_contract(
            "Real Madrid vs Barcelona",
            "Победитель: Real Madrid",
            prediction,
        )

        self.assertIn("Real Madrid 77.8% | Barcelona 22.2%", html)
        self.assertIn("🔢 <b>Прогноз счета:</b> 2:1", html)
        self.assertIn("💡 <b>Анализ:</b> Real Madrid stronger in recent form.", html)

    def test_format_prediction_response_builds_contract_from_raw_response(self):
        raw_response = """
🏆 Победитель: Zenit
📈 Вероятность победы (1-я сторона): 64%
```json
{
  "win_probability_team1": 64,
  "win_probability_team2": 36,
  "recommended_bet_size": 4,
  "exact_score": "2-1",
  "total_prediction": 2.5,
  "total_recommendation": "ТБ 2.5",
  "analysis_summary": "Zenit has the better recent form.",
  "odds": 1.95
}
```
""".strip()

        html = format_prediction_response("Zenit vs CSKA", raw_response)

        self.assertIn("🏆 <b>Победитель:</b> Zenit", html)
        self.assertIn("📈 <b>Вероятность:</b> Zenit 64.0% | CSKA 36.0%", html)
        self.assertIn("🔢 <b>Прогноз счета:</b> 2:1", html)
        self.assertIn("📊 <b>Ожидаемый тотал:</b> 2.5 (ТБ 2.5)", html)
        self.assertIn("Келли: 4.0%", html)

    def test_split_long_message_keeps_each_chunk_within_limit(self):
        text = "\n\n".join(["A" * 60, "B" * 60, "C" * 60])

        parts = split_long_message(text, max_length=100)

        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part) <= 100 for part in parts))

    def test_split_long_message_splits_single_oversized_paragraph_by_lines(self):
        text = "\n".join(["X" * 70, "Y" * 70, "Z" * 70])

        parts = split_long_message(text, max_length=100)

        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[0], "X" * 70)
        self.assertEqual(parts[1], "Y" * 70)
        self.assertEqual(parts[2], "Z" * 70)


    def test_format_response_contract_shows_simple_stake(self):
        prediction = {
            "winner": "Team A",
            "win_probability_team1": 70,
            "win_probability_team2": 30,
            "exact_score": "2:1",
            "total_prediction": 2.5,
            "total_recommendation": "ТБ 2.5",
            "stake_percent": "3%",
            "simple_stake": "3%",
            "analysis_summary": "Test",
            "recommendation": "Ставка",
        }

        html = format_response_contract("Team A vs Team B", "Winner: Team A", prediction)

        self.assertIn("📏 <b>Размер:</b>", html)
        self.assertIn("рекомендация 3%", html)
        self.assertIn("Келли:", html)


if __name__ == "__main__":
    unittest.main()