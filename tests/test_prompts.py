"""Tests for services.prompts — prompt loading."""
import unittest
from pathlib import Path


class TestPrompts(unittest.TestCase):

    def test_load_football_prompt_not_empty(self):
        from services.prompts import load_prompt_file
        text = load_prompt_file("football.md")
        self.assertTrue(len(text) > 50)

    def test_load_nonexistent_returns_empty(self):
        from services.prompts import load_prompt_file
        text = load_prompt_file("nonexistent_sport_xyz.md")
        self.assertEqual(text, "")

    def test_get_discipline_prompt_contains_common_suffix(self):
        from services.prompts import get_discipline_prompt, load_prompt_file
        common = load_prompt_file("common_suffix.md")
        prompt = get_discipline_prompt("футбол")
        self.assertIn(common[:50], prompt)

    def test_get_discipline_prompt_with_key(self):
        from services.prompts import get_discipline_prompt
        prompt = get_discipline_prompt("киберспорт", discipline_key="cs2")
        self.assertTrue(len(prompt) > 50)

    def test_unknown_discipline_returns_nonempty(self):
        from services.prompts import get_discipline_prompt
        prompt = get_discipline_prompt("неизвестный_спорт_xyz")
        # Should return at least common_suffix
        self.assertTrue(len(prompt) > 0)

    def test_all_known_disciplines_load(self):
        from services.prompts import get_discipline_prompt
        disciplines = [
            "футбол", "хоккей", "баскетбол", "теннис", "волейбол",
            "киберспорт", "мма", "бокс", "настольный теннис",
        ]
        for d in disciplines:
            prompt = get_discipline_prompt(d)
            self.assertTrue(len(prompt) > 50, f"Empty prompt for {d}")

    def test_all_esports_subdisciplines_load(self):
        from services.prompts import get_discipline_prompt
        esports = {"cs2": "cs2", "dota2": "dota2", "lol": "lol", "valorant": "valorant"}
        for label, key in esports.items():
            prompt = get_discipline_prompt(label, discipline_key=key)
            self.assertTrue(len(prompt) > 50, f"Empty prompt for {label}")

    def test_all_prompt_files_exist(self):
        from pathlib import Path
        prompts_dir = Path(__file__).parent.parent / "prompts"
        expected_files = [
            "football.md", "hockey.md", "basketball.md", "volleyball.md",
            "tennis.md", "table_tennis.md", "mma.md", "boxing.md",
            "cs2.md", "cybersport.md", "dota2.md", "lol.md", "valorant.md",
            "common_suffix.md",
        ]
        for f in expected_files:
            self.assertTrue((prompts_dir / f).exists(), f"Missing prompt file: {f}")


if __name__ == "__main__":
    unittest.main()
