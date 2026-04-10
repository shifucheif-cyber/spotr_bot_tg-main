"""Tests for services.logging_utils — logging configuration."""
import json
import logging
import os
import tempfile
import unittest
from unittest.mock import patch


class TestConfigureLogging(unittest.TestCase):

    def test_default_level_warning(self):
        from services.logging_utils import configure_logging
        configure_logging(default_level="WARNING")
        root = logging.getLogger()
        self.assertEqual(root.level, logging.WARNING)

    @patch.dict(os.environ, {"APP_LOG_LEVEL": "DEBUG"}, clear=False)
    def test_env_overrides_default(self):
        from services.logging_utils import configure_logging
        configure_logging(default_level="WARNING")
        root = logging.getLogger()
        self.assertEqual(root.level, logging.DEBUG)

    def test_noisy_loggers_suppressed(self):
        from services.logging_utils import configure_logging, NOISY_LOGGERS
        configure_logging()
        for name in NOISY_LOGGERS:
            logger = logging.getLogger(name)
            self.assertGreaterEqual(logger.level, logging.WARNING)

    def test_configure_console_output_no_crash(self):
        from services.logging_utils import configure_console_output
        configure_console_output()

    @patch.dict(os.environ, {"LOG_FORMAT": "json"}, clear=False)
    def test_json_format_output(self):
        from services.logging_utils import configure_logging
        configure_logging(default_level="DEBUG")
        root = logging.getLogger()
        handler = root.handlers[0]
        from services.logging_utils import JsonFormatter
        self.assertIsInstance(handler.formatter, JsonFormatter)

    @patch.dict(os.environ, {"LOG_FORMAT": "text"}, clear=False)
    def test_text_format_is_default(self):
        from services.logging_utils import configure_logging, JsonFormatter
        configure_logging(default_level="DEBUG")
        root = logging.getLogger()
        handler = root.handlers[0]
        self.assertNotIsInstance(handler.formatter, JsonFormatter)

    def test_json_formatter_produces_valid_json(self):
        from services.logging_utils import JsonFormatter
        fmt = JsonFormatter()
        record = logging.LogRecord("test", logging.ERROR, "file", 1, "boom", (), None)
        output = fmt.format(record)
        parsed = json.loads(output)
        self.assertEqual(parsed["level"], "ERROR")
        self.assertEqual(parsed["message"], "boom")
        self.assertIn("ts", parsed)

    def test_error_file_handler(self):
        from services.logging_utils import configure_logging
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            with patch.dict(os.environ, {"LOG_ERROR_FILE": tmp_path}, clear=False):
                configure_logging(default_level="DEBUG")
            logger = logging.getLogger("test_error_file")
            logger.error("test error message")
            with open(tmp_path, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("test error message", content)
            parsed = json.loads(content.strip())
            self.assertEqual(parsed["level"], "ERROR")
        finally:
            # clean up file handler
            root = logging.getLogger()
            root.handlers = [h for h in root.handlers if not isinstance(h, logging.FileHandler)]
            os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
