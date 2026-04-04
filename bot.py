import pytz
from datetime import datetime, timedelta, timezone
import os
import datetime as datetime_module
import re
import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command
from dotenv import load_dotenv
from google.genai import Client as GoogleClient
from google.genai import types as genai_types
from groq import Client as GroqClient

# --- LOCAL IMPORTS ---
from data_router import get_match_data
from services.e2e_summary import emit_quiet_e2e_summary
from services.logging_utils import configure_console_output, configure_logging
from services.match_finder import create_fallback_match_data, format_match_confirmation
from services.prompts import get_discipline_prompt
from services.response_formatter import format_prediction_response, split_long_message
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

# --- CONFIG ---
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

def to_moscow_time(dt: datetime) -> datetime:
    """Преобразует datetime (UTC или naive) в московское время."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MOSCOW_TZ)

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

configure_console_output()
configure_logging(default_level="WARNING")
logger = logging.getLogger(__name__)

TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()
LLM_FALLBACK_ORDER = ["groq", "sambanova", "google", "deepseek"]

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-2.0-pro")
GOOGLE_API_VERSION = os.getenv("GOOGLE_API_VERSION", "v1")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "compound-beta-mini")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com")

SAMBANOVA_API_KEY = os.getenv("SAMBANOVA_API_KEY")
SAMBANOVA_MODEL = os.getenv("SAMBANOVA_MODEL", "Meta-Llama-3.3-70B-Instruct")
SAMBANOVA_BASE_URL = os.getenv("SAMBANOVA_BASE_URL", "https://api.sambanova.ai/v1")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "483078446"))

if not TG_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не задан")

# --- INIT CLIENTS ---
bot = Bot(token=TG_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

google_client = None
if GOOGLE_API_KEY and not GOOGLE_API_KEY.startswith("your_"):
    try:
        google_client = GoogleClient(
            api_key=GOOGLE_API_KEY,
            http_options=genai_types.HttpOptions(api_version=GOOGLE_API_VERSION),
        )
    except Exception as e:
        logger.warning(f"Failed to initialize Google client: {e}")

groq_client = None
if GROQ_API_KEY:
    groq_client = GroqClient(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL or None)

deepseek_client = None
if DEEPSEEK_API_KEY:
    try:
        from openai import AsyncOpenAI
        deepseek_client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    except Exception as e:
        logger.warning(f"Failed to initialize DeepSeek client: {e}")

sambanova_client = None
if SAMBANOVA_API_KEY:
    try:
        from openai import AsyncOpenAI
        sambanova_client = AsyncOpenAI(api_key=SAMBANOVA_API_KEY, base_url=SAMBANOVA_BASE_URL)
    except Exception as e:
        logger.warning(f"Failed to initialize SambaNova client: {e}")

SELECTED_GOOGLE_MODEL = GOOGLE_MODEL

# --- LLM HELPERS ---
GROQ_STABLE_MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "llama3-70b-8192", "llama3-8b-8192"]

def get_available_google_models() -> list[str]:
    if not google_client: return []
    try:
        pager = google_client.models.list(config={"page_size": 50})
        return [m.name for m in pager if any(v in m.name.lower() for v in ["gemini-2", "gemini-3"])]
    except: return []

async def generate_with_google(contents: str, discipline: str, discipline_key: str = None) -> str:
    if not google_client: raise ValueError("Google client not configured")
    system_prompt = get_discipline_prompt(discipline, discipline_key)
    request_contents = f"SYSTEM:\n{system_prompt}\n\nUSER:\n{contents}"
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, lambda: google_client.models.generate_content(model=SELECTED_GOOGLE_MODEL, contents=request_contents))
    return response.text

async def generate_with_groq(contents: str, discipline: str, discipline_key: str = None) -> str:
    if not groq_client: raise ValueError("Groq client not configured")
    system_prompt = get_discipline_prompt(discipline, discipline_key)
    models = [GROQ_MODEL] + [m for m in GROQ_STABLE_MODELS if m != GROQ_MODEL]
    for model in models:
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: groq_client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": contents}],
                max_completion_tokens=2000, temperature=0.2, timeout=30.0
            ))
            if response.choices[0].message.content: return response.choices[0].message.content
        except Exception as e:
            logger.warning(f"Groq {model} failed: {e}")
    raise ValueError("All Groq models failed")

async def generate_with_deepseek(contents: str, discipline: str, discipline_key: str = None) -> str:
    if not deepseek_client: raise ValueError("DeepSeek client not configured")
    system_prompt = get_discipline_prompt(discipline, discipline_key)
    response = await deepseek_client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": contents}],
        max_completion_tokens=2000, temperature=0.2, timeout=30.0
    )
    return response.choices[0].message.content

async def generate_with_sambanova(contents: str, discipline: str, discipline_key: str = None) -> str:
    if not sambanova_client: raise ValueError("SambaNova client not configured")
    system_prompt = get_discipline_prompt(discipline, discipline_key)
    response = await sambanova_client.chat.completions.create(
        model=SAMBANOVA_MODEL,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": contents}],
        max_tokens=2000, temperature=0.2, timeout=30.0
    )
    return response.choices[0].message.content

async def generate_content_with_metadata(contents: str, discipline: str, discipline_key: str = None) -> dict:
    handlers = {"google": generate_with_google, "groq": generate_with_groq, "deepseek": generate_with_deepseek, "sambanova": generate_with_sambanova}
    last_err = None
    for provider in LLM_FALLBACK_ORDER:
        try:
            res = await asyncio.wait_for(handlers[provider](contents, discipline, discipline_key), timeout=60.0)
            if res: return {"provider": provider, "text": res}
        except Exception as e:
            last_err = e
            logger.warning(f"Provider {provider} failed: {e}")
    raise last_err or ValueError("No LLM providers succeeded")

# --- FSM & LOGIC ---
class OrderAnalysis(StatesGroup):
    waiting_discipline = State()
    waiting_subdiscipline = State()
    waiting_team1 = State()
    waiting_team2 = State()
    waiting_date = State()

DISCIPLINE_HIERARCHY = {
    "киберспорт": {"has_subdisciplines": True, "options": {"cs2": "Counter-Strike 2", "lol": "League of Legends", "dota2": "Dota 2", "valorant": "Valorant"}},
    "теннис": {"has_subdisciplines": True, "options": {"tennis": "Большой теннис", "table_tennis": "Настольный теннис"}},
    "мма/бокс": {"has_subdisciplines": True, "options": {"mma": "ММА", "boxing": "Бокс"}},
    "футбол": {"has_subdisciplines": False}, "хоккей": {"has_subdisciplines": False}, "баскетбол": {"has_subdisciplines": False}, "волейбол": {"has_subdisciplines": False}
}

def get_date_keyboard() -> types.InlineKeyboardMarkup:
    today = datetime.now(tz=MOSCOW_TZ)
    kb = []
    for i in range(7):
        date = today + timedelta(days=i)
        date_str = date.strftime("%d.%m.%y")
        label = f"{'Сегодня' if i==0 else ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][date.weekday()]} ({date_str})"
        kb.append([types.InlineKeyboardButton(text=label, callback_data=f"date_{date_str}")])
    return types.InlineKeyboardMarkup(inline_keyboard=kb)

def format_name_correction(label: str, res: dict) -> str:
    return f"{label}: {res['original']} -> {res['corrected']}" if res.get("applied") else f"{label}: {res['corrected']}"

def build_annotation_block(match_text: str) -> str:
    sides = split_match_text(match_text)
    return f"Данные матча:\n1️⃣ {sides[0]}\n2️⃣ {sides[1]}" if len(sides) == 2 else ""

def resolve_match_validation(team1: str, team2: str, date_text: str, disc: str, disc_key: str = None) -> tuple[dict, str, bool]:
    match_text = f"{team1} vs {team2}"
    val = validate_match_request(match_text, date_text, disc_key or disc)
    if val.get("status") == "validated" and val.get("match"):
        match_payload = val["match"]
        if val.get("region"): match_payload["region"] = val["region"]
        return match_payload, val.get("report", ""), True
    
    from services.external_source import search_event_thesportsdb
    event = search_event_thesportsdb(match_text)
    if event:
        return {"sport": disc_key or disc, "home": event.get("strHomeTeam", team1), "away": event.get("strAwayTeam", team2), "date": event.get("dateEvent", date_text), "league": event.get("strLeague", ""), "user_discipline": disc}, "TheSportsDB: найден", True
    
    return create_fallback_match_data(match_text, date_text, disc), val.get("report", ""), False

# --- HANDLERS ---
@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    touch_user(message.from_user, admin_telegram_id=ADMIN_TELEGRAM_ID, increment_requests=True)
    kb = [[types.KeyboardButton(text="киберспорт"), types.KeyboardButton(text="Футбол")], [types.KeyboardButton(text="Теннис"), types.KeyboardButton(text="ММА/Бокс")], [types.KeyboardButton(text="Волейбол"), types.KeyboardButton(text="Хоккей")], [types.KeyboardButton(text="Баскетбол")]]
    await message.answer("🎯 Выберите дисциплину:", reply_markup=types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True))
    await state.set_state(OrderAnalysis.waiting_discipline)

@dp.message(OrderAnalysis.waiting_discipline)
async def set_discipline(message: types.Message, state: FSMContext):
    disc = message.text.strip().lower()
    await state.update_data(discipline=disc)
    if disc in DISCIPLINE_HIERARCHY and DISCIPLINE_HIERARCHY[disc]["has_subdisciplines"]:
        kb = [[types.KeyboardButton(text=label)] for label in DISCIPLINE_HIERARCHY[disc]["options"].values()]
        await message.answer(f"📺 Выбран: {disc}\nВыберите игру:", reply_markup=types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True))
        await state.set_state(OrderAnalysis.waiting_subdiscipline)
    else:
        await message.answer("Введите название первой команды:", reply_markup=types.ReplyKeyboardRemove())
        await state.set_state(OrderAnalysis.waiting_team1)

@dp.message(OrderAnalysis.waiting_subdiscipline)
async def set_subdiscipline(message: types.Message, state: FSMContext):
    label = message.text.strip()
    data = await state.get_data()
    disc = data['discipline']
    key = next((k for k, v in DISCIPLINE_HIERARCHY[disc]["options"].items() if v == label), None)
    if key:
        await state.update_data(subdiscipline=key, full_discipline=f"{disc}: {label}", discipline_key=key)
        await message.answer(f"🎮 {label}\nВведите первую команду:", reply_markup=types.ReplyKeyboardRemove())
        await state.set_state(OrderAnalysis.waiting_team1)
    else: await message.answer("Выберите из списка")

@dp.message(OrderAnalysis.waiting_team1)
async def set_team1(message: types.Message, state: FSMContext):
    data = await state.get_data()
    disc = data.get('full_discipline') or data.get('discipline', '')
    raw = message.text.strip()
    sides = split_match_text(raw)
    if len(sides) == 2:
        t1_res = resolve_entity_name(sides[0], discipline=disc)
        t2_res = resolve_entity_name(sides[1], discipline=disc)
        match = resolve_match_entities(t1_res["corrected"], t2_res["corrected"], discipline=disc)
        await state.update_data(team1=match["team1"]["corrected"], team2=match["team2"]["corrected"], match=match["match"])
        await message.answer(f"🏆 {match['match']}\n{format_name_correction('Т1', t1_res)}\n{format_name_correction('Т2', t2_res)}\n📅 Дата:", reply_markup=get_date_keyboard())
        await state.set_state(OrderAnalysis.waiting_date)
    else:
        res = resolve_entity_name(raw, discipline=disc)
        await state.update_data(team1=res["corrected"])
        await message.answer(f"1️⃣ {format_name_correction('Т1', res)}\nВведите вторую команду:")
        await state.set_state(OrderAnalysis.waiting_team2)

@dp.message(OrderAnalysis.waiting_team2)
async def set_team2(message: types.Message, state: FSMContext):
    data = await state.get_data()
    disc = data.get('full_discipline') or data.get('discipline', '')
    t2_res = resolve_entity_name(message.text.strip(), discipline=disc)
    match = resolve_match_entities(data['team1'], t2_res["corrected"], discipline=disc)
    await state.update_data(team1=match["team1"]["corrected"], team2=match["team2"]["corrected"], match=match["match"])
    await message.answer(f"🏆 {match['match']}\n{format_name_correction('Т2', t2_res)}\n📅 Дата:", reply_markup=get_date_keyboard())
    await state.set_state(OrderAnalysis.waiting_date)

@dp.callback_query(lambda c: c.data.startswith("date_"))
async def handle_date(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    date = callback.data.replace("date_", "")
    await state.update_data(date=date)
    await callback.message.edit_text(f"📅 Дата: {date}")
    data = await state.get_data()
    found, report, valid = resolve_match_validation(data['team1'], data['team2'], date, data.get('full_discipline', data['discipline']), data.get('discipline_key'))
    if found:
        await state.update_data(found_match=found, clarification_type='ok' if valid else 'fallback', match_validation_report=report)
        await callback.message.answer(format_match_confirmation({"status": "ok", "match": found, "needs_confirmation": False}) if valid else f"📊 Анализ: {found['home']} vs {found['away']}")
        await start_analysis(callback.message, state)
    else:
        await callback.message.answer("❌ Ошибка. Введите первую команду заново:")
        await state.set_state(OrderAnalysis.waiting_team1)

async def fetch_match_data(match_name: str, disc: str, ctx: dict, block: str) -> tuple[str, str]:
    try:
        data = await asyncio.wait_for(get_match_data(match_name, disc, match_context=ctx), timeout=120)
    except:
        data = f"Матч: {match_name}\nДата: {ctx.get('date')}\nСбор данных затянулся. Используй доступное."
    payload = f"{data}\n\n{block}\n\n{build_annotation_block(match_name)}"
    return payload, data

async def start_analysis(message: types.Message, state: FSMContext):
    data = await state.get_data()
    status = await message.answer("🔎 Анализирую...")
    try:
        disc = data.get('full_discipline') or data.get('discipline', 'киберспорт')
        m = data.get('found_match') or {}
        match_name = f"{m.get('home','')} vs {m.get('away','')}" or data.get('match')
        ctx = {"date": m.get("date") or data.get("date"), "league": m.get("league", ""), "sport": m.get("sport", ""), "home": m.get("home", ""), "away": m.get("away", "")}

        block = f"Матч: {match_name}\nДата: {ctx['date']}\nЛига: {ctx['league']}\n{data.get('match_validation_report', '')}"
        payload, search_data = await fetch_match_data(match_name, disc, ctx, block)

        # Очистка HTML-тегов из search_data
        clean_search_data = re.sub(r'<[^>]+>', '', search_data) if search_data else ''
        # Вставка статистического блока
        stat_block = f"\n\nCONTEXT DATA FOR ANALYSIS: {clean_search_data}\nPlease identify recent H2H scores and average totals from this text to calculate your prediction. Используй следующие статистические данные для расчета точного счета и тотала: {clean_search_data}. Опирайся на реальные цифры последних встреч."
        full_prompt = f"{payload}\n{stat_block}"

        res = await generate_content_with_metadata(full_prompt, disc, data.get('discipline_key'))

        if res.get("text"):
            record_analysis_result(message.from_user.id, discipline=disc, match_text=match_name, success=True)
            final = format_prediction_response(match_name, res["text"])
            for part in split_long_message(final):
                await message.answer(part, parse_mode="HTML")
        else:
            await message.answer("⚠️ Нет ответа")
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        await message.answer("❌ Ошибка при анализе.")
    finally:
        await status.delete()
        await state.clear()

async def main():
    init_user_store()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
