import json
import logging
import os
import sys
from datetime import datetime, timezone


NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "google_genai",
    "urllib3",
    "openai",
    "groq",
    "asyncio",
)


class JsonFormatter(logging.Formatter):
    """Outputs log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        obj = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(obj, ensure_ascii=False)


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

    use_json = os.getenv("LOG_FORMAT", "").strip().lower() == "json"

    root = logging.getLogger()
    root.setLevel(app_level)
    root.handlers.clear()

    handler = logging.StreamHandler()
    if use_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    root.addHandler(handler)

    error_file = os.getenv("LOG_ERROR_FILE", "").strip()
    if error_file:
        fh = logging.FileHandler(error_file, encoding="utf-8")
        fh.setLevel(logging.ERROR)
        fh.setFormatter(JsonFormatter())
        root.addHandler(fh)

    for logger_name in NOISY_LOGGERS:
        logging.getLogger(logger_name).setLevel(external_level)
