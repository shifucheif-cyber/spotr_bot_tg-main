"""Preflight-проверка окружения перед запуском бота.

Использование:
    python preflight_check.py              # полная проверка
    python preflight_check.py --quiet      # только PASS/WARN/FAIL

Также вызывается автоматически из bot.py при старте.
"""

import importlib
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env")


def run_preflight(quiet: bool = False) -> tuple[str, list[str]]:
    """Проверяет окружение и возвращает (status, messages).

    status: "PASS" | "WARN" | "FAIL"
    messages: список строк для вывода.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1. .env
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        errors.append("FAIL: файл .env не найден")

    # 2. TELEGRAM_TOKEN
    tg_token = os.getenv("TELEGRAM_TOKEN", "")
    if not tg_token or tg_token.startswith("your_"):
        errors.append("FAIL: TELEGRAM_TOKEN не задан или placeholder")

    # 3. Хотя бы один LLM API key
    llm_keys = {
        "GROQ_API_KEY": os.getenv("GROQ_API_KEY", ""),
        "SAMBANOVA_API_KEY": os.getenv("SAMBANOVA_API_KEY", ""),
        "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY", ""),
        "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", ""),
    }
    configured = [k for k, v in llm_keys.items() if v and not v.startswith("your_")]
    if not configured:
        errors.append("FAIL: ни один LLM API key не задан")
    else:
        missing = [k for k, v in llm_keys.items() if not v or v.startswith("your_")]
        if missing and not quiet:
            warnings.append(f"WARN: не заданы ключи: {', '.join(missing)}")

    # 4. Критичные импорты
    critical_modules = ["aiogram", "httpx", "dotenv"]
    optional_modules = {
        "google.genai": "GOOGLE_API_KEY",
        "groq": "GROQ_API_KEY",
        "openai": "DEEPSEEK_API_KEY",  # also used for SambaNova
    }
    for mod in critical_modules:
        try:
            importlib.import_module(mod)
        except ImportError:
            errors.append(f"FAIL: модуль {mod} не найден — проверьте venv и requirements.txt")
    for mod, env_key in optional_modules.items():
        if os.getenv(env_key):
            try:
                importlib.import_module(mod)
            except ImportError:
                warnings.append(f"WARN: модуль {mod} не найден, но ключ {env_key} задан")

    # 5. Bootstrap LLM-клиентов
    try:
        from services.llm_clients import init_llm_clients, get_init_report
        init_errors = init_llm_clients()
        if init_errors and not quiet:
            # не FAIL, а WARN — клиенты могут быть не нужны все
            for provider, reason in init_errors.items():
                if "API key not configured" not in reason:
                    warnings.append(f"WARN: {provider} init: {reason}")
    except Exception as e:
        errors.append(f"FAIL: bootstrap LLM-клиентов упал: {e}")

    # --- итого ---
    if errors:
        return "FAIL", errors + warnings
    if warnings:
        return "WARN", warnings
    return "PASS", ["PASS: все проверки пройдены"]


def main() -> None:
    quiet = "--quiet" in sys.argv
    status, messages = run_preflight(quiet=quiet)
    print(f"=== PREFLIGHT: {status} ===")
    for m in messages:
        print(f"  {m}")
    sys.exit(0 if status == "PASS" else (1 if status == "WARN" else 2))


if __name__ == "__main__":
    main()
