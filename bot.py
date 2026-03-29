import os
import re
import asyncio
import logging

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

# --- LOAD ENV ---
load_dotenv()

logging.basicConfig(level=logging.INFO)

TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-1.5")
GOOGLE_API_VERSION = os.getenv("GOOGLE_API_VERSION", "v1")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "compound-beta-mini")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL")

if not TG_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не задан")

if LLM_PROVIDER == "google":
    if not GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY не задан")
elif LLM_PROVIDER == "groq":
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY не задан")
else:
    raise ValueError("LLM_PROVIDER должен быть 'google' или 'groq'")

# --- INIT ---
bot = Bot(token=TG_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

google_client = None
groq_client = None
SELECTED_GOOGLE_MODEL = GOOGLE_MODEL

if LLM_PROVIDER == "google":
    google_client = GoogleClient(
        api_key=GOOGLE_API_KEY,
        http_options=genai_types.HttpOptions(api_version=GOOGLE_API_VERSION),
    )

    def get_available_models(page_size: int = 50) -> list[str]:
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


    def generate_with_google(contents: str) -> str:
        try:
            response = google_client.models.generate_content(
                model=SELECTED_GOOGLE_MODEL,
                contents=contents,
            )
            return response.text
        except Exception as e:
            text = str(e).lower()
            if "resource_exhausted" in text or "quota exceeded" in text or "too many requests" in text:
                available = get_available_models()
                fallback = [
                    model for model in available
                    if model != SELECTED_GOOGLE_MODEL and ("flash-lite" in model or "lite" in model)
                ]
                for model in fallback:
                    try:
                        logging.warning("Trying fallback model %s after quota error", model)
                        response = google_client.models.generate_content(
                            model=model,
                            contents=contents,
                        )
                        return response.text
                    except Exception as e2:
                        logging.warning("Fallback model %s failed: %s", model, e2)
            raise


    SELECTED_GOOGLE_MODEL = choose_google_model(GOOGLE_MODEL)
    logging.info("Selected Google Generative model: %s", SELECTED_GOOGLE_MODEL)
    logging.info("Google API version: %s", GOOGLE_API_VERSION)
else:
    groq_client = GroqClient(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL or None)
    logging.info("Selected Groq model: %s", GROQ_MODEL)
    logging.info("Groq base URL: %s", groq_client.base_url)


def generate_with_groq(contents: str) -> str:
    try:
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": contents},
            ],
            max_completion_tokens=1024,
            temperature=0.2,
        )
        if not response.choices:
            raise ValueError("Groq response returned no choices")
        return response.choices[0].message.content or ""
    except GroqError as e:
        text = str(e).lower()
        if "model_decommissioned" in text or "decommissioned" in text:
            fallback_models = [
                "compound-beta-mini",
                "compound-beta",
                "qwen/qwen3-32b",
                "openai/gpt-oss-20b",
                "openai/gpt-oss-120b",
            ]
            for model in fallback_models:
                if model == GROQ_MODEL:
                    continue
                try:
                    logging.warning("Groq model %s decommissioned; trying fallback %s", GROQ_MODEL, model)
                    response = groq_client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": SYSTEM_INSTRUCTION},
                            {"role": "user", "content": contents},
                        ],
                        max_completion_tokens=1024,
                        temperature=0.2,
                    )
                    if not response.choices:
                        raise ValueError("Groq response returned no choices")
                    logging.info("Groq fallback model selected: %s", model)
                    return response.choices[0].message.content or ""
                except GroqError as e2:
                    logging.warning("Groq fallback model %s failed: %s", model, e2)
        raise


def generate_content(contents: str) -> str:
    if LLM_PROVIDER == "groq":
        return generate_with_groq(contents)
    return generate_with_google(contents)


logging.info("LLM provider: %s", LLM_PROVIDER)

# --- SYSTEM PROMPT ---
SYSTEM_INSTRUCTION = """
Ты — элитный спортивный аналитик.

СТРОГИЕ ПРАВИЛА:
- Анализируй только указанный матч
- Используй ТОЛЬКО предоставленные данные
- Не выдумывай
- Используй только самые свежие данные
- Для каждого анализа ориентируйся на не менее чем 2 источника
- Если доступен только один источник, обязательно найди второй источник для детальной аналитики
- Не выводи информацию об источниках пользователю напрямую

ЛОГИКА:

Футбол:
- домашнее поле
- составы и ротация
- травмы, дисквалификации, замены
- мотивация, форма, турнирный контекст

Хоккей:
- форма вратаря и спецбригады
- качество льда, домашнее/выездное поле
- травмы и штрафное время
- темп и исполнение большинства

Баскетбол:
- темп и защита
- сила скамейки и ротация
- трёхочковые и подборы
- травмы ключевых игроков

Киберспорт:
- CS2: HLTV, Liquipedia, карты, рейтинги, составы, история личных встреч, замены
- Dota 2: Dotabuff, Stratz, Liquipedia, винрейты героев, составы и текущий патч
- LoL: Oracle's Elixir, Liquipedia, драфт, мета, состояние линий
- формат (Bo1/Bo3/Bo5), пул карт, ротации, замены, форма команды, тренерские правки

Футбол:
- WhoScored / SofaScore: оценки игроков, тепловые карты, прогноз состава, список травм
- Transfermarkt: «вес» команды, трансферы, ротация состава
- Flashscore / MyScore: форма за 5 матчей, H2H, оперативные данные
- домашнее поле, состав, травмы, дисквалификации, мотивация, стиль игры

Хоккей:
- NHL.com / ESPN: продвинутые метрики, отчёты по травмам
- множество: вратарь, спецбригады, лед, домашняя/выездная площадка
- травмы, ротации линий, эффективность большинства, темп

Баскетбол:
- NBA.com / ESPN: продвинутые метрики, отчёты по травмам
- темп и защита, сила скамейки, ротация, трёхочковые, подборы, травмы ключевых игроков

Теннис:
- ATP / WTA Tour: официальный рейтинг, статистика на покрытии, личные встречи
- Tennis Explorer: H2H, фаворит/аутсайдер, текущий график
- покрытие, погодные условия, усталость, подача и приём, мотивация

Настольный теннис:
- TT-Cup / Setka Cup: последние 10-15 матчей, быстрый контроль формы
- скорость и реакция, подача и возврат, стиль игры, тактика, усталость

MMA/Бокс:
- Sherdog / Tapology: история боёв, антропометрия, способ победы
- BoxRec: официальные рейтинги, активность, соперники
- стиль, размах рук, выносливость, весогонка, травмы, защита, борьба

Волейбол:
- WorldofVolley: трансферы, травмы, новости звёзд
- Volleyball World (FIVB): официальные рейтинги, Лига Наций, сборные
- Flashscore / SofaScore: статистика по сетам, форма к 4-5 сету
- CEV / Data Project: европейские чемпионаты, итальянские лиги, эффективность приёма и атаки
- связующий, приём, домашняя площадка, перелёты/jet lag, замены, глубина состава

БАНК:
>80% → 6%
66-80% → 3%
55-65% → 1%
<55% → пропуск

ФОРМАТ:

📊 **Матч:** ...
🏆 **Исход:** ...
📈 **Вероятность:** ...%
💰 **СТАВКА:** ...%

📝 **Суть:**
• Форма:
• Состав:
• Мотивация:
"""

# --- FSM ---
class OrderAnalysis(StatesGroup):
    waiting_discipline = State()
    waiting_match = State()
    waiting_date = State()

# --- HANDLERS ---
@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    kb = [
        [types.KeyboardButton(text="киберспорт"), types.KeyboardButton(text="Футбол")],
        [types.KeyboardButton(text="Теннис"), types.KeyboardButton(text="Настольный теннис")],
        [types.KeyboardButton(text="ММА/Бокс"), types.KeyboardButton(text="Волейбол")],
        [types.KeyboardButton(text="Хоккей"), types.KeyboardButton(text="Баскетбол")]
    ]

    keyboard = types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

    await message.answer("🎯 Выберите дисциплину:", reply_markup=keyboard)
    await state.set_state(OrderAnalysis.waiting_discipline)

@dp.message(OrderAnalysis.waiting_discipline)
async def set_discipline(message: types.Message, state: FSMContext):
    await state.update_data(discipline=message.text)

    await message.answer(
        "Введите матч (пример: Team A vs Team B):",
        reply_markup=types.ReplyKeyboardRemove()
    )

    await state.set_state(OrderAnalysis.waiting_match)

def parse_match_sides(match_text: str) -> list[str]:
    parts = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s*-\s*", match_text, flags=re.I)
    return [part.strip() for part in parts if part.strip()]


def build_annotation_block(match_text: str) -> str:
    sides = parse_match_sides(match_text)
    if len(sides) == 2:
        return (
            "Аннотации по сторонам:\n"
            f"- {sides[0]}: краткая аннотация команды/игрока, стиль, текущая форма и ключевые риски.\n"
            f"- {sides[1]}: краткая аннотация команды/игрока, стиль, текущая форма и ключевые риски."
        )
    return ""


@dp.message(OrderAnalysis.waiting_match)
async def set_match(message: types.Message, state: FSMContext):
    match_text = message.text.strip()
    parts = parse_match_sides(match_text)

    if len(parts) == 1:
        await message.answer(
            "Вы указали только одну команду или фамилию. Пожалуйста, укажите соперника или полный матч в формате 'Team A vs Team B'."
        )
        return

    await state.update_data(match=match_text)

    await message.answer("Введите дату:")
    await state.set_state(OrderAnalysis.waiting_date)

@dp.message(OrderAnalysis.waiting_date)
async def final_step(message: types.Message, state: FSMContext):
    data = await state.get_data()

    full_query = f"{data['match']} {data['discipline']} {message.text}"

    status = await message.answer("🔎 Анализирую матч...")

    try:
        # 🔥 получаем структурированные данные
        search_data = await get_match_data(
            data['match'],
            data['discipline']
        )

        annotation_block = build_annotation_block(data['match'])

        # 🔥 генерим ответ (БЕЗ config!)
        response_text = generate_content(
            f"{SYSTEM_INSTRUCTION}\n\n{search_data}\n\n{annotation_block}"
        )

        await status.delete()

        if response_text:
            await message.answer(response_text, parse_mode="Markdown")
        else:
            await message.answer("⚠️ Нет ответа от модели")

    except Exception as e:
        logging.error(e)
        await message.answer(f"❌ Ошибка: {str(e)}")

    await state.clear()

# --- RUN ---
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
  
if __name__ == "__main__":
    asyncio.run(main())