"""Tests for services.e2e_summary — telemetry output."""
import json
import os
import unittest
from io import StringIO
from unittest.mock import patch


class TestEmitQuietE2ESummary(unittest.TestCase):

    def _call_emit(self, **kwargs):
        defaults = {
            "match_text": "Team A vs Team B",
            "requested_discipline": "футбол",
            "actual_discipline": "футбол",
            "clarification_type": None,
            "search_text": "search data",
            "llm_provider": "groq",
            "final_text": "analysis result text",
        }
        defaults.update(kwargs)
        from services.e2e_summary import emit_quiet_e2e_summary
        emit_quiet_e2e_summary(**defaults)

    @patch.dict(os.environ, {"QUIET_E2E_SUMMARY": "true"}, clear=False)
    def test_enabled_outputs_json(self):
        import importlib
        import services.e2e_summary as mod
        importlib.reload(mod)

        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            mod.emit_quiet_e2e_summary(
                match_text="Team A vs Team B",
                requested_discipline="футбол",
                actual_discipline="футбол",
                clarification_type=None,
                search_text="search data",
                llm_provider="groq",
                final_text="analysis result text",
            )
            output = mock_out.getvalue()

        self.assertTrue(output.strip(), "Expected JSON output but got nothing")
        data = json.loads(output.strip().replace("E2E_SUMMARY=", ""))
        self.assertIn("match", data)

    @patch.dict(os.environ, {"QUIET_E2E_SUMMARY": "false"}, clear=False)
    def test_disabled_outputs_nothing(self):
        import importlib
        import services.e2e_summary as mod
        importlib.reload(mod)

        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            self._call_emit()
            output = mock_out.getvalue()
        self.assertEqual(output.strip(), "")


if __name__ == "__main__":
    unittest.main()
