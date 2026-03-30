import os
import re
import asyncio
import logging
from datetime import datetime, timedelta

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
from services.match_finder import check_match_clarification, format_match_confirmation

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


def generate_with_groq(contents: str, discipline: str = "киберспорт") -> str:
    try:
        system_prompt = get_discipline_prompt(discipline)
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": contents},
            ],
            max_completion_tokens=512,  # Уменьшено с 1024 для избежания ошибок Telegram
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
                    system_prompt = get_discipline_prompt(discipline)
                    response = groq_client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": contents},
                        ],
                        max_completion_tokens=512,
                        temperature=0.2,
                    )
                    if not response.choices:
                        raise ValueError("Groq response returned no choices")
                    logging.info("Groq fallback model selected: %s", model)
                    return response.choices[0].message.content or ""
                except GroqError as e2:
                    logging.warning("Groq fallback model %s failed: %s", model, e2)
        raise


def generate_content(contents: str, discipline: str = "киберспорт") -> str:
    if LLM_PROVIDER == "groq":
        return generate_with_groq(contents, discipline)
    return generate_with_google(contents)


logging.info("LLM provider: %s", LLM_PROVIDER)

# --- OPTIMIZED SYSTEM PROMPTS BY DISCIPLINE ---
DISCIPLINE_PROMPTS = {
    "киберспорт": """Ты - профессиональный аналитик киберспортивных матчей.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные о:
- рейтингах и форме команд  
- истории личных встреч
- составе и подготовке
- картах и стратегиях

Дай четкий прогноз с вероятностью и рекомендацией ставки.""",

    "cs2": """Ты - профессиональный аналитик Counter-Strike 2 матчей.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные о:
- рейтингах HLTV и форме команд на разных картах
- истории личных встреч и победном проценте
- составе и ролях игроков
- пуле карт и тактике

Дай четкий прогноз с вероятностью и рекомендацией ставки.""",

    "lol": """Ты - профессиональный аналитик League of Legends матчей.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные о:
- рейтингах LEC/LPL/Worlds и форме команды
- мета-чемпионах текущего патча  
- составе и специализации игроков по ролям
- истории встреч между командами

Дай четкий прогноз с вероятностью и рекомендацией ставки.""",

    "dota2": """Ты - профессиональный аналитик Dota 2 матчей.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные о:
- винрейтах героев в текущем патче
- истории встреч между командами
- составе и специализации (carry/mid/support)
- недавних турнирах и форме

Дай четкий прогноз с вероятностью и рекомендацией ставки.""",

    "valorant": """Ты - профессиональный аналитик Valorant матчей.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные о:
- форме команды и ведущих игроков
- картах и специализации по агентам
- истории встреч
- недавних турнирах

Дай четкий прогноз с вероятностью и рекомендацией ставки.""",

    "футбол": """Ты - профессиональный аналитик футбольных матчей.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные о:
- форме команд и составе
- травмах и отсутствиях
- домашнем/выездном преимуществе
- истории личных встреч

Дай четкий прогноз с вероятностью и рекомендацией ставки.""",

    "tennis": """Ты - профессиональный аналитик большого тенниса.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные о:
- рейтингах WTA/ATP
- истории личных встреч (H2H) и результатах
- покрытии и условиях игры
- текущей форме и последних турнирах

Дай четкий прогноз с вероятностью и рекомендацией ставки.""",

    "баскетбол": """Ты - профессиональный аналитик баскетбольных матчей.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные о:
- составе и скамейке
- темпе и защите
- истории матчей между командами
- травмах ключевых игроков

Дай четкий прогноз с вероятностью и рекомендацией ставки.""",

    "хоккей": """Ты - профессиональный аналитик хоккейных матчей.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные о:
- форме вратарей и команд
- домашнем/выездном преимуществе
- травмах и ротации лучших игроков
- спецбригадах и последних результатах

Дай четкий прогноз с вероятностью и рекомендацией ставки.""",

    "мма": """Ты - профессиональный аналитик ММА поединков.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные о:
- рекордах и стиле бойцов (нокауты, подмышки, решения)
- боевых опыте и уровне соперничества
- весовой категории и условиях боя
- последних победах/поражениях и мотивации

Дай четкий прогноз с вероятностью и рекомендацией ставки.""",

    "boxing": """Ты - профессиональный аналитик боксёрских матчей.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные о:
- боксёрских рекордах и стиле (бокс, свинг, апперкот)
- опыте соперниках и титулах
- весовой категории и условиях боя
- последних боях и физическом состоянии

Дай четкий прогноз с вероятностью и рекомендацией ставки.""",

    "table_tennis": """Ты - профессиональный аналитик настольного тенниса.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные о:
- рейтингах ITTF
- истории личных встреч и результатах
- стиле игры (защита/атака) и технике
- текущей форме и последних турнирах

Дай четкий прогноз с вероятностью и рекомендацией ставки.""",

    "волейбол": """Ты - профессиональный аналитик волейбольных матчей.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННые данные о:
- рейтингах и составе команд
- эффективности приема и атаки
- домашнем/выездном преимуществе
- последних результатах

Дай четкий прогноз с вероятностью и рекомендацией ставки.""",

}

def get_discipline_prompt(discipline: str) -> str:
    """Получает оптимизированный prompt для дисциплины"""
    from services.match_finder import normalize_discipline
    
    # Если это formato "киберспорт: CS2", извлечем "cs2"
    if ":" in discipline:
        parts = discipline.split(":")
        discipline = parts[1].strip().lower()
    
    norm_disc = normalize_discipline(discipline).lower()
    
    # Пытаемся получить по нормализованному названию
    if norm_disc in DISCIPLINE_PROMPTS:
        return DISCIPLINE_PROMPTS[norm_disc]
    
    # Пытаемся получить по исходному
    if discipline in DISCIPLINE_PROMPTS:
        return DISCIPLINE_PROMPTS[discipline]
    
    # Fallback
    return DISCIPLINE_PROMPTS.get("киберспорт")

# --- SYSTEM PROMPT (DEPRECATED - используем DISCIPLINE_PROMPTS) ---
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
    waiting_subdiscipline = State()  # ДЛЯ КИБЕРСПОРТА: выбор конкретной игры
    waiting_match = State()
    waiting_date = State()
    confirming_match = State()


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
    discipline = message.text.strip().lower()  # ✅ Приводим к нижнему регистру
    await state.update_data(discipline=discipline)

    # Проверяем, есть ли субдисциплины
    if discipline in DISCIPLINE_HIERARCHY and DISCIPLINE_HIERARCHY[discipline].get("has_subdisciplines"):
        # Показываем меню субдисциплин
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
        # Нет субдисциплин, сразу к матчу
        await message.answer(
            "Введите матч (пример: Team A vs Team B):",
            reply_markup=types.ReplyKeyboardRemove()
        )
        await state.set_state(OrderAnalysis.waiting_match)


@dp.message(OrderAnalysis.waiting_subdiscipline)
async def set_subdiscipline(message: types.Message, state: FSMContext):
    """Обработчик выбора субдисциплины (для киберспорта)"""
    data = await state.get_data()
    subdiscipline_label = message.text.strip()
    
    # Найдем ключ по лейблу
    discipline = data.get('discipline', 'киберспорт')
    subdiscipline_key = None
    
    if discipline in DISCIPLINE_HIERARCHY:
        options = DISCIPLINE_HIERARCHY[discipline].get("options", {})
        for key, label in options.items():
            if label == subdiscipline_label:
                subdiscipline_key = key
                break
    
    if subdiscipline_key:
        # Сохраняем полную дисциплину
        full_discipline = f"{discipline}: {subdiscipline_label}"
        await state.update_data(subdiscipline=subdiscipline_key, full_discipline=full_discipline)
        
        await message.answer(
            f"🎮 Дисциплина: {subdiscipline_label}\n\nВведите матч (пример: Team A vs Team B):",
            reply_markup=types.ReplyKeyboardRemove()
        )
        await state.set_state(OrderAnalysis.waiting_match)
    else:
        await message.answer("Пожалуйста, выберите из предложенных вариантов")

def get_date_keyboard() -> types.InlineKeyboardMarkup:
    """Создает клавиатуру с датами на 7 дней от сегодня"""
    today = datetime(2026, 3, 30)  # Фиксированная дата сегодня
    
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
    parts = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s*-\s*", match_text, flags=re.I)
    return [part.strip() for part in parts if part.strip()]


def build_annotation_block(match_text: str) -> str:
    sides = parse_match_sides(match_text)
    if len(sides) == 2:
        return (
            "Данные матча:\n"
            f"1️⃣ {sides[0]}\n"
            f"2️⃣ {sides[1]}"
        )
    return ""


def split_long_message(text: str, max_length: int = 4000) -> list[str]:
    """Разбивает большое сообщение на части (лимит Telegram - 4096)"""
    if len(text) <= max_length:
        return [text]
    
    messages = []
    current = ""
    
    # Разбиваем по абзацам
    paragraphs = text.split("\n\n")
    
    for para in paragraphs:
        if len(current) + len(para) + 2 > max_length:
            if current:
                messages.append(current)
                current = ""
        current += para + "\n\n"
    
    if current:
        messages.append(current)
    
    return [msg.strip() for msg in messages if msg.strip()]


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

    # Показываем календарь для выбора даты
    keyboard = get_date_keyboard()
    await message.answer(
        "📅 Выберите дату матча:",
        reply_markup=keyboard
    )
    await state.set_state(OrderAnalysis.waiting_date)


@dp.callback_query(lambda c: c.data.startswith("date_"))
async def handle_date_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора даты через кнопку календаря"""
    data = await state.get_data()
    
    # Извлекаем дату из callback данных
    date_text = callback.data.replace("date_", "")
    
    await state.update_data(date=date_text)
    
    # Редактируем сообщение - убираем клавиатуру
    await callback.message.edit_text(f"📅 Выбранная дата: {date_text}")
    
    # Используем full_discipline если есть (с субдисциплиной), иначе обычную
    discipline = data.get('full_discipline') or data.get('discipline', '')
    
    # 🔍 Проверяем матч
    clarification = check_match_clarification(
        match_text=data['match'],
        date_text=date_text,
        user_discipline=discipline
    )
    
    # Для callback нужно использовать callback.message вместо message
    
    if clarification and clarification.get('needs_confirmation'):
        # Нужно уточнение
        confirmation_msg = format_match_confirmation(clarification)
        await callback.message.answer(confirmation_msg)
        
        # Сохраняем найденный матч в контексте
        if clarification.get('match'):
            await state.update_data(
                found_match=clarification['match'],
                clarification_type=clarification['status']
            )
        
        await state.set_state(OrderAnalysis.confirming_match)
    elif clarification and not clarification.get('needs_confirmation'):
        # Матч в порядке, начинаем анализ
        await start_analysis(callback.message, state)
    else:
        # Матч не найден в базе, но разрешаем анализ с доступными данными
        from services.match_finder import create_fallback_match_data
        
        fallback_data = create_fallback_match_data(
            match_text=data['match'],
            date_text=date_text,
            discipline=discipline
        )
        
        if fallback_data:
            await state.update_data(found_match=fallback_data)
            await callback.message.answer(
                f"📊 Анализирую матч: **{fallback_data['home']}** vs **{fallback_data['away']}** ({fallback_data['date']})"
            )
            await asyncio.sleep(0.5)
            await start_analysis(callback.message, state)
        else:
            await callback.message.answer(
                "❌ Не удалось разобрать данные матча. Пожалуйста, укажите матч в формате 'Team A vs Team B'"
            )
            await state.clear()
    
    # Удаляем callback-led (уведомления в Telegram)
    await callback.answer()

@dp.message(OrderAnalysis.waiting_date)
async def check_match_text(message: types.Message, state: FSMContext):
    """Альтернативный обработчик - на случай если пользователь введет дату текстом"""
    data = await state.get_data()
    date_text = message.text.strip()
    
    await state.update_data(date=date_text)
    
    # Используем full_discipline если есть (с субдисциплиной), иначе обычную
    discipline = data.get('full_discipline') or data.get('discipline', '')
    
    # 🔍 Проверяем матч
    clarification = check_match_clarification(
        match_text=data['match'],
        date_text=date_text,
        user_discipline=discipline
    )
    
    if clarification and clarification.get('needs_confirmation'):
        # Нужно уточнение
        confirmation_msg = format_match_confirmation(clarification)
        await message.answer(confirmation_msg)
        
        # Сохраняем найденный матч в контексте
        if clarification.get('match'):
            await state.update_data(
                found_match=clarification['match'],
                clarification_type=clarification['status']
            )
        
        await state.set_state(OrderAnalysis.confirming_match)
    elif clarification and not clarification.get('needs_confirmation'):
        # Матч в порядке, начинаем анализ
        await start_analysis(message, state)
    else:
        # Матч не найден в базе, но разрешаем анализ с доступными данными
        from services.match_finder import create_fallback_match_data
        
        fallback_data = create_fallback_match_data(
            match_text=data['match'],
            date_text=date_text,
            discipline=discipline
        )
        
        if fallback_data:
            await state.update_data(found_match=fallback_data)
            await message.answer(
                f"📊 Анализирую матч: **{fallback_data['home']}** vs **{fallback_data['away']}** ({fallback_data['date']})"
            )
            await asyncio.sleep(0.5)
            await start_analysis(message, state)
        else:
            await message.answer(
                "❌ Не удалось разобрать данные матча. Пожалуйста, укажите матч в формате 'Team A vs Team B'"
            )
            await state.clear()


@dp.message(OrderAnalysis.confirming_match)
async def confirm_match(message: types.Message, state: FSMContext):
    """Обработчик подтверждения матча"""
    user_response = message.text.strip().lower()
    data = await state.get_data()
    
    if user_response in ["да", "yes", "y", "д", "ок", "ok"]:
        # Пользователь согласен, начинаем анализ
        await start_analysis(message, state)
    elif user_response in ["нет", "no", "n", "н"]:
        # Пользователь отказался
        await message.answer("❌ Анализ отменён. Попробуйте снова командой /start")
        await state.clear()
    else:
        await message.answer("Пожалуйста, ответьте 'Да' или 'Нет'")


async def start_analysis(message: types.Message, state: FSMContext):
    """Запускает анализ матча"""
    data = await state.get_data()
    
    status = await message.answer("🔎 Анализирую матч...")
    
    try:
        # Используем full_discipline если есть (с субдисциплиной)
        discipline = data.get('full_discipline') or data.get('discipline', 'киберспорт')
        
        # 🔥 получаем структурированные данные
        search_data = await get_match_data(
            data['match'],
            discipline
        )

        annotation_block = build_annotation_block(data['match'])

        # 🔥 генерим ответ с оптимизированным system prompt
        response_text = generate_content(
            f"{search_data}\n\n{annotation_block}",
            discipline=discipline
        )

        await status.delete()

        if response_text:
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