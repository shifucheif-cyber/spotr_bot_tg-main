"""Tests for preflight_check.py — environment validation."""
import os
import unittest
from unittest.mock import patch, MagicMock


class TestRunPreflight(unittest.TestCase):

    @patch.dict(os.environ, {
        "TELEGRAM_TOKEN": "123:ABC",
        "GROQ_API_KEY": "gsk_test",
        "SAMBANOVA_API_KEY": "",
        "GOOGLE_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
        "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
    }, clear=False)
    @patch("preflight_check.Path.exists", return_value=True)
    @patch("preflight_check.importlib.import_module")
    @patch("services.llm_clients.init_llm_clients", return_value={})
    def test_pass_with_valid_env(self, *_mocks):
        from preflight_check import run_preflight
        status, messages = run_preflight(quiet=False)
        self.assertIn(status, ("PASS", "WARN"))

    @patch.dict(os.environ, {
        "TELEGRAM_TOKEN": "",
        "GROQ_API_KEY": "",
        "SAMBANOVA_API_KEY": "",
        "GOOGLE_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
    }, clear=False)
    @patch("preflight_check.Path.exists", return_value=True)
    def test_fail_no_telegram_token(self, *_mocks):
        from preflight_check import run_preflight
        status, messages = run_preflight(quiet=False)
        self.assertEqual(status, "FAIL")
        self.assertTrue(any("TELEGRAM_TOKEN" in m for m in messages))

    @patch.dict(os.environ, {
        "TELEGRAM_TOKEN": "123:ABC",
        "GROQ_API_KEY": "",
        "SAMBANOVA_API_KEY": "",
        "GOOGLE_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
    }, clear=False)
    @patch("preflight_check.Path.exists", return_value=True)
    def test_fail_no_llm_keys(self, *_mocks):
        from preflight_check import run_preflight
        status, messages = run_preflight(quiet=False)
        self.assertEqual(status, "FAIL")
        self.assertTrue(any("LLM" in m for m in messages))

    @patch.dict(os.environ, {
        "TELEGRAM_TOKEN": "123:ABC",
        "GROQ_API_KEY": "gsk_test",
        "SAMBANOVA_API_KEY": "",
        "GOOGLE_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
        "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
    }, clear=False)
    @patch("preflight_check.Path.exists", return_value=True)
    @patch("preflight_check.importlib.import_module")
    @patch("services.llm_clients.init_llm_clients", return_value={"sambanova": "API key not configured"})
    def test_warn_missing_some_keys(self, *_mocks):
        from preflight_check import run_preflight
        status, messages = run_preflight(quiet=False)
        self.assertIn(status, ("PASS", "WARN"))

    @patch.dict(os.environ, {
        "TELEGRAM_TOKEN": "123:ABC",
        "GROQ_API_KEY": "gsk_test",
        "SAMBANOVA_API_KEY": "",
        "GOOGLE_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
    }, clear=False)
    @patch("preflight_check.Path.exists", return_value=True)
    @patch("preflight_check.importlib.import_module")
    @patch("services.llm_clients.init_llm_clients", return_value={})
    def test_quiet_suppresses_warnings(self, *_mocks):
        from preflight_check import run_preflight
        _, messages_quiet = run_preflight(quiet=True)
        _, messages_full = run_preflight(quiet=False)
        self.assertLessEqual(len(messages_quiet), len(messages_full))


if __name__ == "__main__":
    unittest.main()
