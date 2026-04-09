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
        disciplines = ["футбол", "хоккей", "баскетбол", "теннис", "волейбол", "киберспорт"]
        for d in disciplines:
            prompt = get_discipline_prompt(d)
            self.assertTrue(len(prompt) > 50, f"Empty prompt for {d}")


if __name__ == "__main__":
    unittest.main()
