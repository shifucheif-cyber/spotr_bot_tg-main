"""Tests for services.logging_utils — logging configuration."""
import logging
import os
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
        # Should not raise on any platform
        configure_console_output()


if __name__ == "__main__":
    unittest.main()
