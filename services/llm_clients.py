"""Единый bootstrap LLM-клиентов.

Создаёт клиентов Google, Groq, DeepSeek, SambaNova одинаковым способом.
При ошибке инициализации клиент остаётся None, причина сохраняется
в ``init_errors[provider]`` и логируется только на уровне DEBUG.
Подробная диагностика доступна через ``get_init_report()``.
"""

import logging
import os

logger = logging.getLogger(__name__)

# --- результаты bootstrap ---
google_client = None
groq_client = None
deepseek_client = None
sambanova_client = None

init_errors: dict[str, str] = {}

# --- конфигурация из env (заполняется при вызове init_llm_clients) ---
GOOGLE_API_KEY = ""
GOOGLE_MODEL = ""
GOOGLE_API_VERSION = ""
GROQ_API_KEY = ""
GROQ_MODEL = ""
GROQ_BASE_URL = ""
SAMBANOVA_API_KEY = ""
SAMBANOVA_MODEL = ""
SAMBANOVA_BASE_URL = ""
DEEPSEEK_API_KEY = ""
DEEPSEEK_MODEL = ""
DEEPSEEK_BASE_URL = ""

GROQ_STABLE_MODELS: list[str] = []


def init_llm_clients() -> dict[str, str]:
    """Инициализирует всех LLM-клиентов из переменных окружения.

    Возвращает ``init_errors`` — словарь ``{provider: причина}``.
    Если провайдер инициализирован успешно, он отсутствует в словаре.
    """
    global google_client, groq_client, deepseek_client, sambanova_client
    global GOOGLE_API_KEY, GOOGLE_MODEL, GOOGLE_API_VERSION
    global GROQ_API_KEY, GROQ_MODEL, GROQ_BASE_URL, GROQ_STABLE_MODELS
    global SAMBANOVA_API_KEY, SAMBANOVA_MODEL, SAMBANOVA_BASE_URL
    global DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_BASE_URL

    init_errors.clear()

    # --- env ---
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
    GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-2.0-pro")
    GOOGLE_API_VERSION = os.getenv("GOOGLE_API_VERSION", "v1")

    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "compound-beta-mini")
    GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com")

    SAMBANOVA_API_KEY = os.getenv("SAMBANOVA_API_KEY", "")
    SAMBANOVA_MODEL = os.getenv("SAMBANOVA_MODEL", "Meta-Llama-3.3-70B-Instruct")
    SAMBANOVA_BASE_URL = os.getenv("SAMBANOVA_BASE_URL", "https://api.sambanova.ai/v1")

    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    GROQ_STABLE_MODELS = [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "llama3-70b-8192",
        "llama3-8b-8192",
    ]

    # --- Google ---
    google_client = None
    if GOOGLE_API_KEY and not GOOGLE_API_KEY.startswith("your_"):
        try:
            from google.genai import Client as GoogleClient
            from google.genai import types as genai_types

            google_client = GoogleClient(
                api_key=GOOGLE_API_KEY,
                http_options=genai_types.HttpOptions(api_version=GOOGLE_API_VERSION),
            )
        except Exception as e:
            init_errors["google"] = str(e)
            logger.debug("Google client init failed: %s", e)
    else:
        init_errors["google"] = "API key not configured"

    # --- Groq ---
    groq_client = None
    if GROQ_API_KEY:
        try:
            from groq import Client as GroqClient

            groq_client = GroqClient(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL or None)
        except Exception as e:
            init_errors["groq"] = str(e)
            logger.debug("Groq client init failed: %s", e)
    else:
        init_errors["groq"] = "API key not configured"

    # --- DeepSeek ---
    deepseek_client = None
    if DEEPSEEK_API_KEY:
        try:
            from openai import AsyncOpenAI

            deepseek_client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        except Exception as e:
            init_errors["deepseek"] = str(e)
            logger.debug("DeepSeek client init failed: %s", e)
    else:
        init_errors["deepseek"] = "API key not configured"

    # --- SambaNova ---
    sambanova_client = None
    if SAMBANOVA_API_KEY:
        try:
            from openai import AsyncOpenAI

            sambanova_client = AsyncOpenAI(api_key=SAMBANOVA_API_KEY, base_url=SAMBANOVA_BASE_URL)
        except Exception as e:
            init_errors["sambanova"] = str(e)
            logger.debug("SambaNova client init failed: %s", e)
    else:
        init_errors["sambanova"] = "API key not configured"

    return init_errors


def get_init_report() -> str:
    """Человекочитаемый отчёт об инициализации LLM-клиентов."""
    lines = []
    for name, client in [("groq", groq_client), ("sambanova", sambanova_client),
                         ("google", google_client), ("deepseek", deepseek_client)]:
        if client is not None:
            lines.append(f"  {name}: OK")
        else:
            reason = init_errors.get(name, "unknown")
            lines.append(f"  {name}: FAIL — {reason}")
    return "\n".join(lines)
