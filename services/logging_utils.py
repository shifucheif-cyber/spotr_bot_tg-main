import logging
import os
import sys


NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "google_genai",
    "urllib3",
    "openai",
    "groq",
    "asyncio",
)


def configure_console_output() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def configure_logging(default_level: str = "WARNING") -> None:
    app_level_name = os.getenv("APP_LOG_LEVEL", default_level).strip().upper()
    external_level_name = os.getenv("EXTERNAL_LOG_LEVEL", "ERROR").strip().upper()

    app_level = getattr(logging, app_level_name, logging.WARNING)
    external_level = getattr(logging, external_level_name, logging.ERROR)

    logging.basicConfig(
        level=app_level,
        format="%(levelname)s:%(name)s:%(message)s",
        force=True,
    )

    for logger_name in NOISY_LOGGERS:
        logging.getLogger(logger_name).setLevel(external_level)
