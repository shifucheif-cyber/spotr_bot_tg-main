"""Tests for services.llm_clients — LLM bootstrap factory."""
import os
import unittest
from unittest.mock import patch, MagicMock


class TestInitLlmClients(unittest.TestCase):
    """init_llm_clients() с различными конфигурациями env."""

    def _fresh_import(self):
        """Re-import the module to reset global state."""
        import importlib
        import services.llm_clients as mod
        importlib.reload(mod)
        return mod

    @patch.dict(os.environ, {
        "GOOGLE_API_KEY": "", "GROQ_API_KEY": "",
        "SAMBANOVA_API_KEY": "", "DEEPSEEK_API_KEY": "",
    }, clear=False)
    def test_all_keys_empty_fills_init_errors(self):
        mod = self._fresh_import()
        errors = mod.init_llm_clients()
        self.assertIn("google", errors)
        self.assertIn("groq", errors)
        self.assertIn("deepseek", errors)
        self.assertIn("sambanova", errors)
        for reason in errors.values():
            self.assertIn("API key not configured", reason)

    @patch.dict(os.environ, {
        "GOOGLE_API_KEY": "", "GROQ_API_KEY": "",
        "SAMBANOVA_API_KEY": "", "DEEPSEEK_API_KEY": "",
    }, clear=False)
    def test_clients_are_none_when_no_keys(self):
        mod = self._fresh_import()
        mod.init_llm_clients()
        self.assertIsNone(mod.google_client)
        self.assertIsNone(mod.groq_client)
        self.assertIsNone(mod.deepseek_client)
        self.assertIsNone(mod.sambanova_client)

    @patch.dict(os.environ, {
        "GOOGLE_API_KEY": "", "GROQ_API_KEY": "",
        "SAMBANOVA_API_KEY": "", "DEEPSEEK_API_KEY": "",
    }, clear=False)
    def test_get_init_report_returns_string(self):
        mod = self._fresh_import()
        mod.init_llm_clients()
        report = mod.get_init_report()
        self.assertIsInstance(report, str)
        self.assertIn("google", report.lower())

    @patch.dict(os.environ, {
        "GOOGLE_API_KEY": "", "GROQ_API_KEY": "",
        "SAMBANOVA_API_KEY": "", "DEEPSEEK_API_KEY": "",
    }, clear=False)
    def test_double_init_does_not_crash(self):
        mod = self._fresh_import()
        mod.init_llm_clients()
        errors2 = mod.init_llm_clients()
        self.assertIsInstance(errors2, dict)

    @patch.dict(os.environ, {"GROQ_API_KEY": "test-key-123"}, clear=False)
    def test_groq_key_set_attempts_client_creation(self):
        mod = self._fresh_import()
        with patch.object(mod, "groq_client", None):
            errors = mod.init_llm_clients()
            # Client may fail due to proxy/network, but key should be read
            self.assertEqual(mod.GROQ_API_KEY, "test-key-123")


if __name__ == "__main__":
    unittest.main()
