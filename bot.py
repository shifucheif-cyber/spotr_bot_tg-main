import os
import re
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command

from dotenv import load_dotenv
from google.genai import Client as GoogleClient
from google.genai import types as genai_types
from groq import Client as GroqClient, GroqError

from data_router import get_match_data
from services.e2e_summary import emit_quiet_e2e_summary
from services.logging_utils import configure_console_output, configure_logging
from services.match_finder import check_match_clarification, create_fallback_match_data, format_match_confirmation
from services.name_normalizer import resolve_entity_name, resolve_match_entities, split_match_text
from services.search_engine import validate_match_request
from services.user_store import (
    get_stats_summary,
    get_user_details,
    init_user_store,
    list_recent_users,
    log_user_event,
    record_analysis_result,
    touch_user,
)

# --- LOAD ENV ---
load_dotenv()

configure_console_output()
configure_logging(default_level="WARNING")
logger = logging.getLogger(__name__)

TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()
LLM_FALLBACK_ORDER = ["google", "groq", "deepseek"]

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-1.5")
GOOGLE_API_VERSION = os.getenv("GOOGLE_API_VERSION", "v1")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "compound-beta-mini")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "483078446"))

if not TG_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не задан")

if not any([GOOGLE_API_KEY, GROQ_API_KEY, DEEPSEEK_API_KEY]):
    raise ValueError("Не задан ни один LLM API key: нужен хотя бы один из GOOGLE_API_KEY, GROQ_API_KEY или DEEPSEEK_API_KEY")

if LLM_PROVIDER not in {"google", "groq", "deepseek"}:
    logger.warning("Unsupported LLM_PROVIDER=%s. Unified fallback order will be used: %s", LLM_PROVIDER, " -> ".join(LLM_FALLBACK_ORDER))

# --- INIT ---
bot = Bot(token=TG_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Принудительная инициализация обоих клиентов для возможности переключения
google_client = None
if GOOGLE_API_KEY and not GOOGLE_API_KEY.startswith("your_"):
    try:
        google_client = GoogleClient(
            api_key=GOOGLE_API_KEY,
            http_options=genai_types.HttpOptions(api_version=GOOGLE_API_VERSION),
        )
        logging.info("Google client initialized for fallback")
    except Exception as e:
        logging.warning(f"Failed to initialize Google client: {e}")
else:
    logging.info("Google API key is missing or placeholder; Gemini fallback disabled")

groq_client = None

deepseek_client = None
if DEEPSEEK_API_KEY:
    try:
        from openai import AsyncOpenAI

        deepseek_client = AsyncOpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL
        )
        logging.info("DeepSeek client initialized")
    except ImportError:
        logging.warning("OpenAI package is not installed; DeepSeek provider disabled")
    except Exception as e:
        logging.warning(f"Failed to initialize DeepSeek client: {e}")
else:
    logging.info("DeepSeek API key is missing; DeepSeek provider disabled")

SELECTED_GOOGLE_MODEL = GOOGLE_MODEL

def get_available_models(page_size: int = 50) -> list[str]:
    if not google_client:
        return []
    try:
        pager = google_client.models.list(config={"page_size": page_size})
        available = [model.name for model in pager]
        logging.info("Available Google models: %s", available)
        return available
    except Exception as e:
        logging.warning("Unable to list available Google models: %s", e)
        return []


def choose_google_model(default_model: str) -> str:
    available = get_available_models()
    if not available:
        logging.info("No available models returned, using default model: %s", default_model)
        return default_model

    for model in available:
        if model == default_model or model.endswith(f"/{default_model}"):
            logging.info("Using requested model: %s", model)
            return model

    preferred = [
        default_model,
        "gemini-2.0-flash-lite-001",
        "gemini-2.0-flash-lite",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash-001",
        "gemini-2.0-flash",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-1.5-proto",
        "gemini-2.0",
        "gemini-1.0",
        "text-bison@001",
    ]
    for candidate in preferred:
        for model in available:
            if model == candidate or model.endswith(f"/{candidate}") or candidate in model:
                logging.info("Switching to available model: %s", model)
                return model

    logging.warning("Preferred models not found; using first available model: %s", available[0])
    return available[0]


SELECTED_GOOGLE_MODEL = choose_google_model(GOOGLE_MODEL)
logging.info("Selected Google Generative model: %s", SELECTED_GOOGLE_MODEL)
logging.info("Google API version: %s", GOOGLE_API_VERSION)

if GROQ_API_KEY:
    groq_client = GroqClient(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL or None)
    logging.info("Selected Groq model: %s", GROQ_MODEL)
    logging.info("Groq base URL: %s", groq_client.base_url)
else:
    logging.info("Groq API key is missing; Groq provider disabled")


# --- LLM MODELS TO TRY ---
GROQ_STABLE_MODELS = [
    "llama-3.3-70b-versatile",
    "mixtral-8x7b-32768",
    "llama-3.1-8b-instant",
    "llama3-70b-8192",
    "llama3-8b-8192",
]


def _create_groq_request(model_name: str, system_prompt: str, contents: str):
    """Helper function for Groq API call to avoid lambda late binding issues."""
    return groq_client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": contents},
        ],
        max_completion_tokens=2000,
        temperature=0.2,
        timeout=30.0
    )


def build_google_contents(system_prompt: str, contents: str) -> str:
    return f"SYSTEM:\n{system_prompt}\n\nUSER:\n{contents}"


async def generate_with_google(contents: str, discipline: str = "киберспорт", discipline_key: str = None) -> str:
    """Async Google Gemini content generation with fallback support."""
    if not google_client or not SELECTED_GOOGLE_MODEL:
        raise ValueError("Google Gemini client is not configured (API key is missing or SELECTED_GOOGLE_MODEL is empty)")

    system_prompt = get_discipline_prompt(discipline, discipline_key)
    request_contents = build_google_contents(system_prompt, contents)

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: google_client.models.generate_content(
                model=SELECTED_GOOGLE_MODEL,
                contents=request_contents,
            )
        )
        return response.text
    except Exception as e:
        text = str(e).lower()
        # Try fallback model if quota exceeded
        if "resource_exhausted" in text or "quota exceeded" in text or "too many requests" in text:
            available = get_available_models()
            fallback = [
                model for model in available
                if model != SELECTED_GOOGLE_MODEL and ("flash-lite" in model or "lite" in model)
            ]
            for model in fallback:
                try:
                    logging.warning("Trying fallback model %s after quota error", model)
                    loop = asyncio.get_event_loop()
                    response = await loop.run_in_executor(
                        None,
                        lambda: google_client.models.generate_content(
                            model=model,
                            contents=request_contents,
                        )
                    )
                    return response.text
                except Exception as e2:
                    logging.warning("Fallback model %s failed: %s", model, e2)
        raise


async def generate_with_groq(contents: str, discipline: str = "киберспорт", discipline_key: str = None) -> str:
    """Async Groq content generation with multiple model fallback."""
    if not groq_client:
        raise ValueError("Groq client is not configured (API key is missing)")

    # Пытаемся сначала использовать основной модель из .env
    models_to_try = [GROQ_MODEL] + [m for m in GROQ_STABLE_MODELS if m != GROQ_MODEL]
    
    last_error = None
    system_prompt = get_discipline_prompt(discipline, discipline_key)

    for model_name in models_to_try:
        try:
            logger.info(f"Trying Groq model: {model_name}...")
            loop = asyncio.get_event_loop()
            # Use helper function instead of lambda to avoid late binding issues
            response = await loop.run_in_executor(
                None, 
                _create_groq_request,
                model_name,
                system_prompt,
                contents
            )
            
            if response.choices and response.choices[0].message.content:
                logger.info(f"Successfully generated content with {model_name}")
                return response.choices[0].message.content
        except Exception as e:
            last_error = e
            logger.warning(f"Groq model {model_name} failed: {e}")
            # Пауза перед следующей попыткой при сетевой ошибке
            if "connection" in str(e).lower():
                await asyncio.sleep(1)
            continue

    # Если и Gemini нет, кидаем последнюю ошибку Groq
    if last_error:
        raise last_error
    raise ValueError("Failed to generate content with any available LLM provider")


async def generate_with_deepseek(contents: str, discipline: str = "киберспорт", discipline_key: str = None) -> str:
    """Async DeepSeek content generation."""
    if not deepseek_client:
        raise ValueError("DeepSeek client is not configured (API key is missing)")
    
    try:
        system_prompt = get_discipline_prompt(discipline, discipline_key)
        response = await deepseek_client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": contents},
            ],
            max_completion_tokens=2000,
            temperature=0.2,
            timeout=30.0
        )
        
        if response.choices and response.choices[0].message.content:
            logger.info(f"Successfully generated content with DeepSeek model {DEEPSEEK_MODEL}")
            return response.choices[0].message.content
        raise ValueError("DeepSeek returned empty response")
    except Exception as e:
        logger.error(f"DeepSeek generation failed: {e}")
        raise


async def generate_content(contents: str, discipline: str = "киберспорт", discipline_key: str = None) -> str:
    response = await generate_content_with_metadata(contents, discipline=discipline, discipline_key=discipline_key)
    return response["text"]


async def generate_content_with_metadata(contents: str, discipline: str = "киберспорт", discipline_key: str = None) -> dict:
    provider_handlers = {
        "deepseek": generate_with_deepseek,
        "google": generate_with_google,
        "groq": generate_with_groq,
    }
    last_error = None

    logger.info("LLM fallback order: %s", " -> ".join(LLM_FALLBACK_ORDER))

    for provider_name in LLM_FALLBACK_ORDER:
        handler = provider_handlers[provider_name]
        try:
            logger.info("Trying LLM provider: %s", provider_name)
            response = await asyncio.wait_for(
                handler(contents, discipline, discipline_key),
                timeout=60.0,
            )
            if response and response.strip():
                logger.info("LLM provider succeeded: %s", provider_name)
                return {"provider": provider_name, "text": response}
            raise ValueError(f"{provider_name} returned empty response")
        except asyncio.TimeoutError:
            last_error = TimeoutError(f"{provider_name} timed out after 60s")
            logger.warning("LLM provider %s timed out", provider_name)
            continue
        except Exception as exc:
            last_error = exc
            logger.warning("LLM provider %s failed: %s", provider_name, exc)
            continue

    if last_error:
        raise last_error
    raise ValueError("No available LLM providers succeeded")


logging.info("Configured LLM provider hint: %s", LLM_PROVIDER)

# --- OPTIMIZED SYSTEM PROMPTS BY DISCIPLINE ---
DISCIPLINE_PROMPTS = {
    "киберспорт": """Ты - профессиональный аналитик киберспортивных матчей.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные.

**ОБЯЗАТЕЛЬНЫЙ ФОРМАТ ОТВЕТА:**
📊 **Матч:** [Команда А] vs [Команда Б]
📅 **Дата:** [Дата]

📝 **Анализ команд:**
• **[Команда А]:** (1-2 предложения о текущей форме, ключевых игроках и последних результатах).
• **[Команда Б]:** (1-2 предложения о текущей форме, ключевых игроках и последних результатах).

🔍 **Ключевые факторы:**
• (Фактор 1: маппул, личные встречи или замены)
• (Фактор 2: мотивация или турнирное положение)

📈 **Вероятность победы (1-я команда):** X%

""",

    "cs2": """Ты - профессиональный аналитик Counter-Strike 2 матчей.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные (HLTV, Liquipedia и др.).

**ОБЯЗАТЕЛЬНЫЙ ФОРМАТ ОТВЕТА:**
📊 **Матч:** [Команда А] vs [Команда Б]
📅 **Дата:** [Дата]

📝 **Анализ команд:**
• **[Команда А]:** (1-2 предложения о винрейтах на картах, форме лидеров и последних результатах на HLTV).
• **[Команда Б]:** (1-2 предложения о винрейтах на картах, форме лидеров и последних результатах на HLTV).

🔍 **Ключевые факторы:**
• (Фактор 1: маппул и бан-пик карт)
• (Фактор 2: история личных встреч H2H)

📈 **Вероятность победы (1-я команда):** X%

""",

    "lol": """Ты - профессиональный аналитик League of Legends матчей.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные.

**ОБЯЗАТЕЛЬНЫЙ ФОРМАТ ОТВЕТА:**
📊 **Матч:** [Команда А] vs [Команда Б]
📅 **Дата:** [Дата]

📝 **Анализ команд:**
• **[Команда А]:** (1-2 предложения о текущей форме, мете и ключевых игроках).
• **[Команда Б]:** (1-2 предложения о текущей форме, мете и ключевых игроках).

🔍 **Ключевые факторы:**
• (Фактор 1: драфт и приоритетные чемпионы)
• (Фактор 2: контроль объектов и ранняя игра)

📈 **Вероятность победы (1-я команда):** X%

""",

    "dota2": """Ты - профессиональный аналитик Dota 2 матчей.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные (Dotabuff, Liquipedia).

**ОБЯЗАТЕЛЬНЫЙ ФОРМАТ ОТВЕТА:**
📊 **Матч:** [Команда А] vs [Команда Б]
📅 **Дата:** [Дата]

📝 **Анализ команд:**
• **[Команда А]:** (1-2 предложения о пуле героев, форме коров и последних сериях).
• **[Команда Б]:** (1-2 предложения о пуле героев, форме коров и последних сериях).

🔍 **Ключевые факторы:**
• (Фактор 1: влияние текущего патча на стратегии)
• (Фактор 2: синергия саппортов и ранний прессинг)

📈 **Вероятность победы (1-я команда):** X%

""",

    "valorant": """Ты - профессиональный аналитик Valorant матчей.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные.

**ОБЯЗАТЕЛЬНЫЙ ФОРМАТ ОТВЕТА:**
📊 **Матч:** [Команда А] vs [Команда Б]
📅 **Дата:** [Дата]

📝 **Анализ команд:**
• **[Команда А]:** (1-2 предложения о выборе агентов, форме дуэлянтов и последних результатах).
• **[Команда Б]:** (1-2 предложения о выборе агентов, форме дуэлянтов и последних результатах).

🔍 **Ключевые факторы:**
• (Фактор 1: статистика на выбранных картах)
• (Фактор 2: индивидуальный скилл ключевых игроков)

📈 **Вероятность победы (1-я команда):** X%

""",

    "футбол": """Ты - профессиональный аналитик футбольных матчей.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные (WhoScored, Transfermarkt, Flashscore).

**ОБЯЗАТЕЛЬНЫЙ ФОРМАТ ОТВЕТА:**
📊 **Матч:** [Команда А] vs [Команда Б]
📅 **Дата:** [Дата]

📝 **Анализ команд:**
• **[Команда А]:** (1-2 предложения о текущей серии, травмах лидеров и стиле игры дома/в гостях).
• **[Команда Б]:** (1-2 предложения о текущей серии, травмах лидеров и стиле игры дома/в гостях).

🔍 **Ключевые факторы:**
• (Фактор 1: отсутствие ключевых игроков из-за дисквалификаций/травм)
• (Фактор 2: тактическое противостояние тренеров)

📈 **Вероятность победы (1-я команда):** X%

""",

    "tennis": """Ты - профессиональный аналитик большого тенниса.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные (ATP/WTA, Tennis Explorer).

**ОБЯЗАТЕЛЬНЫЙ ФОРМАТ ОТВЕТА:**
📊 **Матч:** [Игрок А] vs [Игрок Б]
📅 **Дата:** [Дата]

📝 **Анализ игроков:**
• **[Игрок А]:** (1-2 предложения о форме на текущем покрытии, физическом состоянии и последних турнирах).
• **[Игрок Б]:** (1-2 предложения о форме на текущем покрытии, физическом состоянии и последних турнирах).

🔍 **Ключевые факторы:**
• (Фактор 1: статистика личных встреч H2H на этом покрытии)
• (Фактор 2: психологическая устойчивость и мотивация)

📈 **Вероятность победы (1-й игрок):** X%

""",

    "баскетбол": """Ты - профессиональный аналитик баскетбольных матчей.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные (NBA.com, ESPN).

**ОБЯЗАТЕЛЬНЫЙ ФОРМАТ ОТВЕТА:**
📊 **Матч:** [Команда А] vs [Команда Б]
📅 **Дата:** [Дата]

📝 **Анализ команд:**
• **[Команда А]:** (1-2 предложения о результативности, силе скамейки и форме лидеров).
• **[Команда Б]:** (1-2 предложения о результативности, силе скамейки и форме лидеров).

🔍 **Ключевые факторы:**
• (Фактор 1: темп игры и эффективность защиты)
• (Фактор 2: доминирование в краске и подборы)

📈 **Вероятность победы (1-я команда):** X%

""",

    "хоккей": """Ты - профессиональный аналитик хоккейных матчей.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные (NHL.com, Flashscore).

**ОБЯЗАТЕЛЬНЫЙ ФОРМАТ ОТВЕТА:**
📊 **Матч:** [Команда А] vs [Команда Б]
📅 **Дата:** [Дата]

📝 **Анализ команд:**
• **[Команда А]:** (1-2 предложения о форме вратаря, игре в большинстве и последних матчах).
• **[Команда Б]:** (1-2 предложения о форме вратаря, игре в большинстве и последних матчах).

🔍 **Ключевые факторы:**
• (Фактор 1: надежность защиты и спецбригады меньшинства)
• (Фактор 2: история встреч в текущем сезоне)

📈 **Вероятность победы (1-я команда):** X%

""",

    "мма": """Ты - профессиональный аналитик ММА поединков.
Анализируй ТОЛЬКО указанный бой, используя ПОЛУЧЕННые данные (Sherdog, Tapology).

**ОБЯЗАТЕЛЬНЫЙ ФОРМАТ ОТВЕТА:**
📊 **Бой:** [Боец А] vs [Боец Б]
📅 **Дата:** [Дата]

📝 **Анализ бойцов:**
• **[Боец А]:** (1-2 предложения о стиле боя, последних победах и физической форме).
• **[Боец Б]:** (1-2 предложения о стиле боя, последних победах и физической форме).

🔍 **Ключевые факторы:**
• (Фактор 1: преимущество в антропометрии или опыте)
• (Фактор 2: весогонка и тренировочный лагерь)

📈 **Вероятность победы (1-й боец):** X%

""",

    "boxing": """Ты - профессиональный аналитик боксёрских матчей.
Анализируй ТОЛЬКО указанный бой, используя ПОЛУЧЕННые данные (BoxRec).

**ОБЯЗАТЕЛЬНЫЙ ФОРМАТ ОТВЕТА:**
📊 **Бой:** [Боксёр А] vs [Боксёр Б]
📅 **Дата:** [Дата]

📝 **Анализ боксёров:**
• **[Боксёр А]:** (1-2 предложения о рекорде, стиле и последнем выступлении).
• **[Боксёр Б]:** (1-2 предложения о рекорде, стиле и последнем выступлении).

🔍 **Ключевые факторы:**
• (Фактор 1: ударная мощь и работа ног)
• (Фактор 2: уровень оппозиции в последних боях)

📈 **Вероятность победы (1-й боксёр):** X%

""",

    "table_tennis": """Ты - профессиональный аналитик настольного тенниса.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные (TT-Cup, Setka Cup).

**ОБЯЗАТЕЛЬНЫЙ ФОРМАТ ОТВЕТА:**
📊 **Матч:** [Игрок А] vs [Игрок Б]
📅 **Дата:** [Дата]

📝 **Анализ игроков:**
• **[Игрок А]:** (1-2 предложения о текущей серии побед, стиле игры и выносливости).
• **[Игрок Б]:** (1-2 предложения о текущей серии побед, стиле игры и выносливости).

🔍 **Ключевые факторы:**
• (Фактор 1: история личных встреч за последние 10-15 матчей)
• (Фактор 2: психологическая устойчивость в решающих сетах)

📈 **Вероятность победы (1-й игрок):** X%

""",

    "волейбол": """Ты - профессиональный аналитик волейбольных матчей.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные (Volleyball World, Flashscore).

**ОБЯЗАТЕЛЬНЫЙ ФОРМАТ ОТВЕТА:**
📊 **Матч:** [Команда А] vs [Команда Б]
📅 **Дата:** [Дата]

📝 **Анализ команд:**
• **[Команда А]:** (1-2 предложения о приеме, атаке и форме связующего).
• **[Команда Б]:** (1-2 предложения о приеме, атаке и форме связующего).

🔍 **Ключевые факторы:**
• (Фактор 1: глубина состава и наличие лидеров)
• (Фактор 2: домашнее преимущество и jet lag)

📈 **Вероятность победы (1-я команда):** X%

""",
}

OUTPUT_CONTRACT_SUFFIX = """

МЕТОДОЛОГИЯ АНАЛИЗА (выполняй строго по шагам):

ШАГ 1 — ИЗВЛЕЧЕНИЕ ФАКТОВ. Из полученных данных выпиши КОНКРЕТНЫЕ факты:
- Последние результаты каждой стороны (серии побед/поражений, счета)
- Личные встречи (H2H) — кто побеждал, с каким счётом
- Травмы, дисквалификации, отсутствие ключевых игроков
- Текущая позиция в турнирной таблице, стадия плей-офф
- Домашнее/выездное преимущество

ШАГ 2 — ВЗВЕШИВАНИЕ. Для каждого факта определи: в чью пользу он работает?
Запиши: «[Факт] → преимущество [Сторона А / Сторона Б / нейтрально]»

ШАГ 3 — ВЫВОД. Подсчитай, у кого больше значимых преимуществ.
Чем больше одна сторона доминирует по фактам — тем дальше вероятность от 50%.
Если факты примерно равны — вероятность близка к 50% (пропуск ставки).

КРИТИЧЕСКОЕ ПРАВИЛО: Победитель = сторона с вероятностью > 50%. Вероятность 2-й стороны = 100 - P.

ПРАВИЛА ФОРМАТА СЧЁТА (поле «Прогноз по счету»):
- Футбол: голы, например «2:1», «0:0»
- Хоккей: голы (основное время), например «3:2», «1:2 OT»
- Баскетбол: очки, например «105:98», «112:109»
- Волейбол: сеты, например «3:1», «3:2»
- Теннис: сеты, например «2:1», «2:0» (или «3:1» для Grand Slam)
- Настольный теннис: сеты, например «3:2», «3:1»
- CS2: карты, например «2:0», «2:1»
- Dota 2: карты, например «2:1», «2:0»
- LoL: карты, например «2:1», «3:1»
- Valorant: карты, например «2:1», «2:0»
- ММА: метод победы и раунд, например «KO R2», «Decision (Unanimous)», «Submission R1»
- Бокс: метод победы и раунд, например «TKO R8», «UD 12 rounds», «KO R3»

Шкала ставок:
- P > 80% или P < 20% → 5% (ультра-уверенность)
- 66–80% или 20–34% → 3% (высокая)
- 55–65% или 35–45% → 1% (рискованно)
- 45–55% → ⚠️ ПРОПУСТИТЬ

ФИНАЛЬНЫЙ ОБЯЗАТЕЛЬНЫЙ ФОРМАТ ОТВЕТА:
📊 **Матч:** <команда/игрок 1> vs <команда/игрок 2>

📋 **Факты из данных:**
- (факт 1 → преимущество [сторона])
- (факт 2 → преимущество [сторона])
- (факт 3 → преимущество [сторона])
- ...

📝 **Анализ:**
• **[Сторона А]:** (вывод из фактов)
• **[Сторона Б]:** (вывод из фактов)

📈 **Вероятность победы (1-я сторона):** P% (на основе баланса фактов выше)
🏆 **Победитель:** <сторона с P > 50%>
🔢 **Прогноз по счету:** <по правилам формата счёта для данной дисциплины>
💰 **Рекомендуемый % от банка:** X%
"""

def get_discipline_prompt(discipline: str, discipline_key: str = None) -> str:
    """Получает оптимизированный prompt для дисциплины"""
    from services.match_finder import normalize_discipline
    
    # Если передан прямой ключ (например, 'cs2'), используем его сразу
    if discipline_key and discipline_key in DISCIPLINE_PROMPTS:
        return DISCIPLINE_PROMPTS[discipline_key] + OUTPUT_CONTRACT_SUFFIX
    
    # Если это формат "киберспорт: CS2", извлечем "cs2"
    if ":" in discipline:
        parts = discipline.split(":")
        discipline = parts[1].strip().lower()
    
    norm_disc = normalize_discipline(discipline).lower()
    
    # Пытаемся получить по нормализованному названию
    if norm_disc in DISCIPLINE_PROMPTS:
        return DISCIPLINE_PROMPTS[norm_disc] + OUTPUT_CONTRACT_SUFFIX
    
    # Пытаемся получить по исходному
    if discipline in DISCIPLINE_PROMPTS:
        return DISCIPLINE_PROMPTS[discipline] + OUTPUT_CONTRACT_SUFFIX
    
    # Fallback
    return DISCIPLINE_PROMPTS.get("киберспорт") + OUTPUT_CONTRACT_SUFFIX

# --- FSM ---
class OrderAnalysis(StatesGroup):
    waiting_discipline = State()
    waiting_subdiscipline = State()  # ДЛЯ КИБЕРСПОРТА: выбор конкретной игры
    waiting_team1 = State()          # Первая команда/игрок
    waiting_team2 = State()          # Вторая команда/игрок
    waiting_date = State()


# --- ДИСЦИПЛИНЫ С СУБКАТЕГОРИЯМИ ---
DISCIPLINE_HIERARCHY = {
    "киберспорт": {
        "has_subdisciplines": True,
        "options": {
            "cs2": "Counter-Strike 2",
            "lol": "League of Legends", 
            "dota2": "Dota 2",
            "valorant": "Valorant"
        }
    },
    "теннис": {
        "has_subdisciplines": True,
        "options": {
            "tennis": "Большой теннис",
            "table_tennis": "Настольный теннис"
        }
    },
    "мма/бокс": {
        "has_subdisciplines": True,
        "options": {
            "mma": "ММА",
            "boxing": "Бокс"
        }
    },
    "футбол": {"has_subdisciplines": False},
    "хоккей": {"has_subdisciplines": False},
    "баскетбол": {"has_subdisciplines": False},
    "настольный теннис": {"has_subdisciplines": False},
    "волейбол": {"has_subdisciplines": False},
}

# --- HANDLERS ---
@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    touch_user(message.from_user, admin_telegram_id=ADMIN_TELEGRAM_ID, increment_requests=True)
    log_user_event(message.from_user.id, "start")
    kb = [
        [types.KeyboardButton(text="киберспорт"), types.KeyboardButton(text="Футбол")],
        [types.KeyboardButton(text="Теннис"), types.KeyboardButton(text="ММА/Бокс")],
        [types.KeyboardButton(text="Волейбол"), types.KeyboardButton(text="Хоккей")],
        [types.KeyboardButton(text="Баскетбол")]
    ]

    keyboard = types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

    await message.answer("🎯 Выберите дисциплину:", reply_markup=keyboard)
    await state.set_state(OrderAnalysis.waiting_discipline)

@dp.message(OrderAnalysis.waiting_discipline)
async def set_discipline(message: types.Message, state: FSMContext):
    discipline = message.text.strip().lower()
    logging.info(f"User {message.from_user.id} selected discipline: {discipline}")
    touch_user(message.from_user, admin_telegram_id=ADMIN_TELEGRAM_ID, discipline=discipline)
    log_user_event(message.from_user.id, "select_discipline", {"discipline": discipline})
    await state.update_data(discipline=discipline)

    if discipline in DISCIPLINE_HIERARCHY and DISCIPLINE_HIERARCHY[discipline].get("has_subdisciplines"):
        subdisbut = DISCIPLINE_HIERARCHY[discipline]["options"]
        kb = []
        for key, label in subdisbut.items():
            kb.append([types.KeyboardButton(text=label)])
        
        keyboard = types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
        await message.answer(
            f"📺 Выбран: {discipline}\n\nТеперь выберите конкретную игру:",
            reply_markup=keyboard
        )
        await state.set_state(OrderAnalysis.waiting_subdiscipline)
    else:
        await message.answer(
            "Введите название первой команды (или игрока):",
            reply_markup=types.ReplyKeyboardRemove()
        )
        await state.set_state(OrderAnalysis.waiting_team1)


@dp.message(OrderAnalysis.waiting_subdiscipline)
async def set_subdiscipline(message: types.Message, state: FSMContext):
    data = await state.get_data()
    subdiscipline_label = message.text.strip()
    logging.info(f"User {message.from_user.id} selected subdiscipline: {subdiscipline_label}")
    touch_user(message.from_user, admin_telegram_id=ADMIN_TELEGRAM_ID)
    log_user_event(message.from_user.id, "select_subdiscipline", {"subdiscipline": subdiscipline_label})
    
    discipline = data.get('discipline', 'киберспорт')
    subdiscipline_key = None
    
    if discipline in DISCIPLINE_HIERARCHY:
        options = DISCIPLINE_HIERARCHY[discipline].get("options", {})
        for key, label in options.items():
            if label == subdiscipline_label:
                subdiscipline_key = key
                break
    
    if subdiscipline_key:
        full_discipline = f"{discipline}: {subdiscipline_label}"
        await state.update_data(
            subdiscipline=subdiscipline_key, 
            full_discipline=full_discipline,
            discipline_key=subdiscipline_key  # Сохраняем ключ для промпта
        )
        
        await message.answer(
            f"🎮 Дисциплина: {subdiscipline_label}\n\nВведите название первой команды (или игрока):",
            reply_markup=types.ReplyKeyboardRemove()
        )
        await state.set_state(OrderAnalysis.waiting_team1)
    else:
        await message.answer("Пожалуйста, выберите из предложенных вариантов")

def get_date_keyboard() -> types.InlineKeyboardMarkup:
    """Создает клавиатуру с датами на 7 дней от сегодня (MSK, UTC+3)"""
    msk = timezone(timedelta(hours=3))
    today = datetime.now(tz=msk)
    
    kb = []
    for i in range(7):
        date = today + timedelta(days=i)
        date_str = date.strftime("%d.%m.%y")
        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][date.weekday()]
        
        if i == 0:
            label = f"Сегодня ({date_str})"
        else:
            label = f"{day_name} {date_str}"
        
        kb.append([types.InlineKeyboardButton(text=label, callback_data=f"date_{date_str}")])
    
    return types.InlineKeyboardMarkup(inline_keyboard=kb)


def parse_match_sides(match_text: str) -> list[str]:
    return split_match_text(match_text)


def format_name_correction(label: str, resolution: dict) -> str:
    if not resolution.get("applied"):
        return f"{label}: {resolution['corrected']}"
    return f"{label}: {resolution['original']} -> {resolution['corrected']}"


def build_annotation_block(match_text: str) -> str:
    sides = parse_match_sides(match_text)
    if len(sides) == 2:
        return (
            "Данные матча:\n"
            f"1️⃣ {sides[0]}\n"
            f"2️⃣ {sides[1]}"
        )
    return ""


def resolve_match_validation(team1: str, team2: str, date_text: str, discipline: str, discipline_key: str | None = None) -> tuple[dict, str, bool]:
    match_text = f"{team1} vs {team2}"
    validation = validate_match_request(match_text, date_text, discipline_key or discipline)
    if validation.get("status") == "validated" and validation.get("match"):
        return validation["match"], validation.get("report", ""), True
    return create_fallback_match_data(match_text, date_text, discipline), validation.get("report", ""), False


def _check_source_quality(search_data: str) -> bool:
    """
    Check if search_data contains validated sources.
    Returns True if has real validated data, False if only fallback/template data.
    """
    if not search_data:
        return False
    # Check for the validation marker from services
    has_validated = "Валидация: validated" in search_data or "Подтверждено источников:" in search_data
    return has_validated


def _extract_contract_field(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip(" -*")
    return ""


def format_response_contract(match_text: str, raw_analysis: str, prediction_struct: dict) -> str:
    """
    Format final response as enforced contract with required fields.
    Uses structured probability field, not text parsing.
    """
    # Strip JSON blocks from raw analysis (internal data, not for user)
    cleaned_analysis = re.sub(r'```json\s*\{.*?\}\s*```', '', raw_analysis, flags=re.DOTALL).strip()
    # Also strip bare JSON objects that look like our contract block
    cleaned_analysis = re.sub(r'\{\s*"winner".*?\}', '', cleaned_analysis, flags=re.DOTALL).strip()

    prob = prediction_struct.get("probability")
    stake = prediction_struct.get("stake_percent")
    
    winner = _extract_contract_field(cleaned_analysis, [r"Победитель:\s*(.+)", r"Исход:\s*(.+)", r"Прогноз победителя:\s*(.+)"])
    total = _extract_contract_field(cleaned_analysis, [r"Общий тотал:\s*(.+)", r"Тотал карт:\s*(.+)", r"Тотал:\s*(.+)"])
    score = _extract_contract_field(cleaned_analysis, [r"Прогноз по счету:\s*(.+)", r"Прогноз по сч[её]ту / картам / сетам:\s*(.+)", r"Сч[её]т:\s*(.+)"])
    
    prob_text = f"{prob:.0f}%" if prob is not None else "не определена"
    stake_text = str(stake) if stake is not None else "ПРОПУСК"
    
    contract = [
        "═══════════════════════════════════════",
        "СТРУКТУРИРОВАННЫЙ ПРОГНОЗ",
        "═══════════════════════════════════════",
        f"📊 Матч: {match_text}",
        f"🏆 Победитель: {winner or '?'}",
        f"🎯 Тотал: {total or '?'}",
        f"🔢 Счет: {score or '?'}",
        f"📈 Вероятность: {prob_text}",
        f"💰 Ставка: {stake_text}",
        f"💡 Детали: {prediction_struct.get('recommendation', 'Нет данных')}",
        "═══════════════════════════════════════",
        "",
        "📝 ПОЛНЫЙ АНАЛИЗ:",
        cleaned_analysis,
    ]
    
    return "\n".join(contract)


def split_long_message(text: str, max_length: int = 4000) -> list[str]:
    """Разбивает большое сообщение на части (лимит Telegram - 4096)"""
    if len(text) <= max_length:
        return [text]
    
    messages = []
    current = ""
    
    # Разбиваем по абзацам
    paragraphs = text.split("\n\n")
    
    for para in paragraphs:
        # Если один абзац длиннее лимита — режем по строкам
        if len(para) > max_length:
            if current:
                messages.append(current)
                current = ""
            lines = para.split("\n")
            for line in lines:
                if len(current) + len(line) + 1 > max_length:
                    if current:
                        messages.append(current)
                    current = ""
                current += line + "\n"
            continue
        if len(current) + len(para) + 2 > max_length:
            if current:
                messages.append(current)
                current = ""
        current += para + "\n\n"
    
    if current:
        messages.append(current)
    
    return [msg.strip() for msg in messages if msg.strip()]


def is_admin_user(user_id: int) -> bool:
    return user_id == ADMIN_TELEGRAM_ID


def format_stats_report() -> str:
    stats = get_stats_summary()
    discipline_lines = "\n".join(
        f"- {discipline}: {count}" for discipline, count in stats["top_disciplines"]
    ) or "- нет данных"
    return (
        "📊 Статистика бота\n\n"
        f"Всего пользователей: {stats['total_users']}\n"
        f"Активны за 24ч: {stats['active_day']}\n"
        f"Активны за 7 дней: {stats['active_week']}\n"
        f"Активны за 30 дней: {stats['active_month']}\n"
        f"Всего запросов: {stats['total_requests']}\n"
        f"Всего анализов: {stats['total_analyses']}\n"
        f"Успешных анализов: {stats['successful_analyses']}\n"
        f"Активных подписок: {stats['active_subscriptions']}\n\n"
        "Топ дисциплин:\n"
        f"{discipline_lines}"
    )


def format_recent_users_report() -> str:
    users = list_recent_users(limit=20)
    if not users:
        return "Пользователей пока нет"

    lines = ["👥 Последние пользователи"]
    for user in users:
        display_name = user.get("username") or user.get("first_name") or str(user["telegram_user_id"])
        admin_mark = " [admin]" if user.get("is_admin") else ""
        lines.append(
            f"- {display_name} | id={user['telegram_user_id']} | last_seen={user['last_seen']} | req={user['requests_count']} | analyses={user['analyses_count']} | sub={user['subscription_status']}{admin_mark}"
        )
    return "\n".join(lines)


def format_user_details_report(telegram_user_id: int) -> str:
    details = get_user_details(telegram_user_id)
    if not details:
        return f"Пользователь {telegram_user_id} не найден"

    event_lines = []
    for event in details["recent_events"]:
        event_lines.append(f"- {event['event_time']} | {event['event_type']} | {event['details_json']}")

    events_text = "\n".join(event_lines) if event_lines else "- нет событий"
    return (
        f"👤 Пользователь {telegram_user_id}\n\n"
        f"username: {details.get('username')}\n"
        f"first_name: {details.get('first_name')}\n"
        f"last_name: {details.get('last_name')}\n"
        f"first_seen: {details.get('first_seen')}\n"
        f"last_seen: {details.get('last_seen')}\n"
        f"requests_count: {details.get('requests_count')}\n"
        f"analyses_count: {details.get('analyses_count')}\n"
        f"successful_analyses: {details.get('successful_analyses')}\n"
        f"subscription_status: {details.get('subscription_status')}\n"
        f"subscription_until: {details.get('subscription_until')}\n"
        f"last_discipline: {details.get('last_discipline')}\n"
        f"last_match: {details.get('last_match')}\n"
        f"is_admin: {bool(details.get('is_admin'))}\n\n"
        "Последние события:\n"
        f"{events_text}"
    )


async def deny_admin_access(message: types.Message) -> None:
    await message.answer("⛔ Команда доступна только администратору")


@dp.message(Command("stats"))
async def admin_stats(message: types.Message):
    touch_user(message.from_user, admin_telegram_id=ADMIN_TELEGRAM_ID)
    if not is_admin_user(message.from_user.id):
        await deny_admin_access(message)
        return
    log_user_event(message.from_user.id, "admin_stats")
    await message.answer(format_stats_report())


@dp.message(Command("users"))
async def admin_users(message: types.Message):
    touch_user(message.from_user, admin_telegram_id=ADMIN_TELEGRAM_ID)
    if not is_admin_user(message.from_user.id):
        await deny_admin_access(message)
        return
    log_user_event(message.from_user.id, "admin_users")
    await message.answer(format_recent_users_report())


@dp.message(Command("user"))
async def admin_user_details(message: types.Message):
    touch_user(message.from_user, admin_telegram_id=ADMIN_TELEGRAM_ID)
    if not is_admin_user(message.from_user.id):
        await deny_admin_access(message)
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip().isdigit():
        await message.answer("Использование: /user <telegram_user_id>")
        return

    target_user_id = int(parts[1].strip())
    log_user_event(message.from_user.id, "admin_user_details", {"target_user_id": target_user_id})
    await message.answer(format_user_details_report(target_user_id))


@dp.message(OrderAnalysis.waiting_team1)
async def set_team1(message: types.Message, state: FSMContext):
    data = await state.get_data()
    discipline = data.get('full_discipline') or data.get('discipline', '')
    raw_input = message.text.strip()
    sides = parse_match_sides(raw_input)

    # Поддержка старого UX: пользователь может сразу ввести "Team A vs Team B" или "Team A против Team B".
    if len(sides) == 2:
        team1_resolution = resolve_entity_name(sides[0], discipline=discipline)
        team2_resolution = resolve_entity_name(sides[1], discipline=discipline)
        resolved_match = resolve_match_entities(team1_resolution["corrected"], team2_resolution["corrected"], discipline=discipline)
        team1 = resolved_match["team1"]["corrected"]
        team2 = resolved_match["team2"]["corrected"]
        match_text = resolved_match["match"]

        touch_user(message.from_user, admin_telegram_id=ADMIN_TELEGRAM_ID, match_text=match_text)
        log_user_event(
            message.from_user.id,
            "set_match_direct",
            {
                "team1": team1,
                "team2": team2,
                "match": match_text,
            },
        )

        await state.update_data(
            team1=team1,
            team2=team2,
            team1_original=team1_resolution["original"],
            team2_original=team2_resolution["original"],
            match=match_text,
        )

        keyboard = get_date_keyboard()
        await message.answer(
            (
                f"🏆 Матч: {team1} vs {team2}\n"
                f"{format_name_correction('Первая команда', team1_resolution)}\n"
                f"{format_name_correction('Соперник', team2_resolution)}\n\n"
                "📅 Выберите дату матча:"
            ),
            reply_markup=keyboard
        )
        await state.set_state(OrderAnalysis.waiting_date)
        return

    resolution = resolve_entity_name(raw_input, discipline=discipline)
    team1 = resolution["corrected"]
    touch_user(message.from_user, admin_telegram_id=ADMIN_TELEGRAM_ID, match_text=team1)
    log_user_event(message.from_user.id, "set_team1", {"team1": team1, "original": resolution["original"], "reason": resolution["reason"]})
    await state.update_data(team1=team1, team1_original=resolution["original"])
    await message.answer(
        f"1️⃣ {format_name_correction('Первая команда', resolution)}\n\nТеперь введите название второй команды (соперника):"
    )
    await state.set_state(OrderAnalysis.waiting_team2)


@dp.message(OrderAnalysis.waiting_team2)
async def set_team2(message: types.Message, state: FSMContext):
    data = await state.get_data()
    discipline = data.get('full_discipline') or data.get('discipline', '')
    team1 = data.get('team1')
    team2_resolution = resolve_entity_name(message.text.strip(), discipline=discipline)
    team2 = team2_resolution["corrected"]
    resolved_match = resolve_match_entities(team1, team2, discipline=discipline)
    team1 = resolved_match["team1"]["corrected"]
    team2 = resolved_match["team2"]["corrected"]
    match_text = resolved_match["match"]
    touch_user(message.from_user, admin_telegram_id=ADMIN_TELEGRAM_ID, match_text=match_text)
    log_user_event(
        message.from_user.id,
        "set_team2",
        {
            "team2": team2,
            "team2_original": team2_resolution["original"],
            "match": match_text,
        },
    )
    await state.update_data(
        team1=team1,
        team2=team2,
        team2_original=team2_resolution["original"],
        match=match_text,
    )

    # Показываем календарь для выбора даты
    keyboard = get_date_keyboard()
    await message.answer(
        (
            f"🏆 Матч: {team1} vs {team2}\n"
            f"{format_name_correction('Соперник', team2_resolution)}\n\n"
            "📅 Выберите дату матча:"
        ),
        reply_markup=keyboard
    )
    await state.set_state(OrderAnalysis.waiting_date)


@dp.callback_query(lambda c: c.data.startswith("date_"))
async def handle_date_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора даты через кнопку календаря"""
    # Сразу отвечаем на колбэк, чтобы кнопка не "висела" нажатой и не истек таймаут Telegram
    try:
        await callback.answer()
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    data = await state.get_data()
    
    # Извлекаем дату из callback данных
    date_text = callback.data.replace("date_", "")
    touch_user(callback.from_user, admin_telegram_id=ADMIN_TELEGRAM_ID)
    log_user_event(callback.from_user.id, "select_date", {"date": date_text})
    
    await state.update_data(date=date_text)
    
    # Редактируем сообщение - убираем клавиатуру
    await callback.message.edit_text(f"📅 Выбранная дата: {date_text}")
    
    # 🔍 Проверяем матч
    discipline = data.get('full_discipline') or data.get('discipline', '')
    team1 = data.get('team1')
    team2 = data.get('team2')
    
    found_match, validation_report, was_validated = resolve_match_validation(
        team1,
        team2,
        date_text,
        discipline,
        discipline_key=data.get('discipline_key'),
    )

    if found_match:
        await state.update_data(
            found_match=found_match,
            clarification_type='ok' if was_validated else 'fallback',
            match_validation_report=validation_report,
        )
        if was_validated:
            confirmation_msg = format_match_confirmation({"status": "ok", "match": found_match, "needs_confirmation": False})
            await callback.message.answer(confirmation_msg)
        else:
            await callback.message.answer(
                f"📊 Анализирую матч: **{found_match['home']}** vs **{found_match['away']}** ({found_match['date']})"
            )
        await asyncio.sleep(0.5)
        await start_analysis(callback.message, state)
    else:
        await callback.message.answer(
            "❌ Не удалось разобрать данные матча. Пожалуйста, укажите матч в формате 'Team A vs Team B' или 'Team A против Team B'"
        )
        await state.update_data(team1=None, team2=None, match=None, found_match=None)
        await callback.message.answer("Введите название первой команды (или игрока) заново:")
        await state.set_state(OrderAnalysis.waiting_team1)
    
    # Старый ответ в конце удаляем
    # try:
    #     await callback.answer()
    # except Exception as e:
    #     logger.warning(f"Failed to answer callback query: {e}")

@dp.message(OrderAnalysis.waiting_date)
async def check_match_text(message: types.Message, state: FSMContext):
    """Альтернативный обработчик - на случай если пользователь введет дату текстом"""
    data = await state.get_data()
    date_text = message.text.strip()
    touch_user(message.from_user, admin_telegram_id=ADMIN_TELEGRAM_ID)
    log_user_event(message.from_user.id, "input_date", {"date": date_text})
    
    await state.update_data(date=date_text)
    
    # Используем full_discipline если есть (с субдисциплиной), иначе обычную
    discipline = data.get('full_discipline') or data.get('discipline', '')
    team1 = data.get('team1')
    team2 = data.get('team2')
    
    found_match, validation_report, was_validated = resolve_match_validation(
        team1,
        team2,
        date_text,
        discipline,
        discipline_key=data.get('discipline_key'),
    )

    if found_match:
        await state.update_data(
            found_match=found_match,
            clarification_type='ok' if was_validated else 'fallback',
            match_validation_report=validation_report,
        )
        if was_validated:
            await message.answer(format_match_confirmation({"status": "ok", "match": found_match, "needs_confirmation": False}))
        else:
            await message.answer(f"📊 Анализирую матч: **{found_match['home']}** vs **{found_match['away']}** ({found_match['date']})")
        await start_analysis(message, state)
    else:
        await message.answer("❌ Не удалось разобрать данные матча. Пожалуйста, укажите матч в формате 'Team A vs Team B' или 'Team A против Team B'")
        await state.update_data(team1=None, team2=None, match=None, found_match=None)
        await message.answer("Введите название первой команды (или игрока) заново:")
        await state.set_state(OrderAnalysis.waiting_team1)


async def start_analysis(message: types.Message, state: FSMContext):
    """Запускает анализ матча"""
    data = await state.get_data()
    
    status = await message.answer("🔎 Анализирую матч...")
    
    try:  # noqa: the finally block ensures status message cleanup
        # Используем full_discipline если есть (с субдисциплиной)
        discipline = data.get('full_discipline') or data.get('discipline', 'киберспорт')
        discipline_key = data.get('discipline_key')
        found_match = data.get('found_match') or {}
        analysis_match = data.get('match')

        if found_match.get('home') and found_match.get('away'):
            analysis_match = f"{found_match['home']} vs {found_match['away']}"

        match_context = {
            "date": found_match.get("date") or data.get("date"),
            "league": found_match.get("league", ""),
            "sport": found_match.get("sport", ""),
            "home": found_match.get("home", ""),
            "away": found_match.get("away", ""),
        }
        touch_user(
            message.from_user,
            admin_telegram_id=ADMIN_TELEGRAM_ID,
            discipline=discipline,
            match_text=analysis_match,
        )
        log_user_event(
            message.from_user.id,
            "analysis_started",
            {"discipline": discipline, "match": analysis_match, "date": match_context.get("date")},
        )
        context_block = "\n".join(
            line for line in [
                f"Подтвержденный матч: {analysis_match}" if analysis_match else "",
                f"Дата матча: {match_context['date']}" if match_context.get('date') else "",
                f"Лига/турнир: {match_context['league']}" if match_context.get('league') else "",
                data.get('match_validation_report', ''),
            ] if line
        )
        
        # 🔥 получаем структурированные данные
        try:
            search_data = await asyncio.wait_for(
                get_match_data(
                    analysis_match,
                    discipline,
                    match_context=match_context,
                ),
                timeout=120,
            )
        except asyncio.TimeoutError:
            logger.warning("Timed out collecting search data for %s", analysis_match)
            search_data = (
                f"Матч: {analysis_match}\n"
                f"Дата: {match_context.get('date') or 'не указана'}\n"
                "Быстрый сбор подтвержденных источников занял слишком много времени. "
                "Продолжай анализ на основе уже известных вводных и явно пометь ограничения по данным."
            )

        annotation_block = build_annotation_block(analysis_match)
        
        # 🔍 Проверяем качество собранных источников
        sources_quality = _check_source_quality(search_data)
        quality_notice = ""
        if not sources_quality:
            quality_notice = (
                "\n⚠️ ПРИМЕЧАНИЕ О КАЧЕСТВЕ ДАННЫХ:\n"
                "Валидированные источники не найдены или отсутствуют.\n"
                "Анализ выполняется на основе доступных данных и шаблонных рекомендаций.\n"
                "Уверенность в прогнозе СНИЖЕНА. Отметьте это в ответе пользователю.\n"
            )
        
        request_payload = f"{search_data}{quality_notice}\n\n{context_block}\n\n{annotation_block}" if context_block else f"{search_data}{quality_notice}\n\n{annotation_block}"

        # 🔥 генерим ответ с оптимизированным system prompt
        content_metadata = await generate_content_with_metadata(
            request_payload,
            discipline=discipline,
            discipline_key=discipline_key,
        )
        response_text = content_metadata["text"]

        if response_text:
            record_analysis_result(
                message.from_user.id,
                discipline=discipline,
                match_text=analysis_match,
                success=True,
            )
            # 💰 Извлекаем вероятность и рекомендацию по ставке
            from services.betting_calculator import get_bet_recommendation
            prediction_struct = get_bet_recommendation(response_text)
            response_text = format_response_contract(analysis_match, response_text, prediction_struct)

            emit_quiet_e2e_summary(
                match_text=analysis_match,
                requested_discipline=discipline,
                actual_discipline=match_context.get("sport", ""),
                clarification_type=data.get("clarification_type"),
                search_text=search_data,
                llm_provider=content_metadata.get("provider", "unknown"),
                final_text=response_text,
            )
            
            # Разбиваем большие сообщения
            parts = split_long_message(response_text)
            for i, part in enumerate(parts):
                try:
                    await message.answer(part, parse_mode="Markdown")
                    if i < len(parts) - 1:
                        await asyncio.sleep(0.5)  # Небольшая задержка между частями
                except Exception as e:
                    logging.error(f"Error sending message part {i+1}: {e}")
                    await message.answer(f"⚠️ Ошибка отправки части {i+1}")
        else:
            emit_quiet_e2e_summary(
                match_text=analysis_match,
                requested_discipline=discipline,
                actual_discipline=match_context.get("sport", ""),
                clarification_type=data.get("clarification_type"),
                search_text=search_data,
                llm_provider=content_metadata.get("provider", "unknown"),
                final_text="no response from model",
            )
            record_analysis_result(
                message.from_user.id,
                discipline=discipline,
                match_text=analysis_match,
                success=False,
            )
            await message.answer("⚠️ Нет ответа от модели")

    except Exception as e:
        logging.error(e)
        emit_quiet_e2e_summary(
            match_text=data.get('match') or "",
            requested_discipline=data.get('full_discipline') or data.get('discipline') or "",
            actual_discipline=(data.get('found_match') or {}).get('sport', ''),
            clarification_type=data.get('clarification_type'),
            search_text="",
            llm_provider="unknown",
            final_text=f"error: {e}",
        )
        record_analysis_result(
            message.from_user.id,
            discipline=data.get('full_discipline') or data.get('discipline'),
            match_text=data.get('match'),
            success=False,
        )
        log_user_event(message.from_user.id, "analysis_exception", {"error": str(e)})
        if "No available LLM providers" in str(e):
            await message.answer("⚙️ Сервисы ИИ временно недоступны. Пожалуйста, попробуйте позже.")
        elif "quota" in str(e).lower() or "rate limit" in str(e).lower():
            await message.answer("⚙️ Сервисы ИИ перегружены (лимит запросов). Пожалуйста, попробуйте через пару минут.")
        else:
            logging.error("Unhandled analysis error: %s", e, exc_info=True)
            await message.answer("❌ Произошла ошибка при анализе. Попробуйте позже или выберите другой матч.")
    finally:
        try:
            await status.delete()
        except Exception:
            pass

    await state.clear()

# --- RUN ---
async def _periodic_cache_cleanup():
    """Фоновая задача: раз в сутки удаляет записи кэша старше 2 дней."""
    from services.data_fetcher import cleanup_expired_cache
    while True:
        await asyncio.sleep(24 * 3600)  # раз в сутки
        removed = cleanup_expired_cache()
        logger.info("Daily cache cleanup: removed %d stale entries", removed)


async def main():
    init_user_store()
    asyncio.create_task(_periodic_cache_cleanup())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
  
if __name__ == "__main__":
    asyncio.run(main())
