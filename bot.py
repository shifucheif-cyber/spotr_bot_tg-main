import itertools
import pytz
from datetime import datetime, timedelta, timezone
import os
import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command
from dotenv import load_dotenv

# --- LOCAL IMPORTS ---
from data_router import get_match_data
from services.logging_utils import configure_console_output, configure_logging
from services import llm_clients
from services.match_finder import create_fallback_match_data, format_match_confirmation
from services.prompts import get_discipline_prompt
from services.response_formatter import format_prediction_response, split_long_message
from services.name_normalizer import resolve_entity_name, resolve_match_entities, split_match_text
from services.search_engine import validate_match_request
from services.external_source import search_event_thesportsdb
from services.user_store import (
    init_user_store,
    record_analysis_result,
    touch_user,
    check_daily_limit,
    increment_daily_request,
)
from services.analysis_cache import analysis_cache_key, get_cached_analysis, put_cached_analysis
from services.event_phase import EventPhase, get_event_phase, is_event_expired

# --- CONFIG ---
ENABLE_PAYWALL = os.getenv("ENABLE_PAYWALL", "false").lower() in ("true", "1", "yes")
_ANALYSIS_TIMEOUT = int(os.getenv("ANALYSIS_TIMEOUT", "300"))
_user_semaphores: dict[int, asyncio.Semaphore] = {}


def _sanitize_user_input(text: str, max_len: int = 100) -> str | None:
    """Validate and sanitize user-supplied text (team names, etc.).

    Returns cleaned text or None if invalid.
    """
    if not text:
        return None
    # Remove control characters except space
    cleaned = "".join(c for c in text if c == " " or (c.isprintable() and ord(c) >= 0x20))
    cleaned = cleaned.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len]
    return cleaned
MAX_FREE_REQUESTS = int(os.getenv("MAX_FREE_REQUESTS", "3"))
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

configure_console_output()
configure_logging(default_level="WARNING")
logger = logging.getLogger(__name__)

TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
LLM_FALLBACK_ORDER = ["groq", "sambanova", "google", "deepseek"]
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "483078446"))

if not TG_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не задан")

# --- INIT CLIENTS (тихий bootstrap) ---
llm_clients.init_llm_clients()

bot = Bot(token=TG_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- LLM HELPERS ---

async def generate_with_google(contents: str, discipline: str, discipline_key: str = None) -> str:
    client = llm_clients.google_client
    if not client:
        raise ValueError(f"Google client not initialized: {llm_clients.init_errors.get('google', 'unknown')}")
    system_prompt = get_discipline_prompt(discipline, discipline_key)
    request_contents = f"SYSTEM:\n{system_prompt}\n\nUSER:\n{contents}"
    response = await client.aio.models.generate_content(model=llm_clients.GOOGLE_MODEL, contents=request_contents)
    return response.text

async def generate_with_groq(contents: str, discipline: str, discipline_key: str = None) -> str:
    client = llm_clients.groq_client
    if not client:
        raise ValueError(f"Groq client not initialized: {llm_clients.init_errors.get('groq', 'unknown')}")
    system_prompt = get_discipline_prompt(discipline, discipline_key)
    models = [llm_clients.GROQ_MODEL] + [m for m in llm_clients.GROQ_STABLE_MODELS if m != llm_clients.GROQ_MODEL]
    for model in models:
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": contents}],
                max_completion_tokens=2000, temperature=0.2, timeout=15.0
            )
            if response.choices[0].message.content: return response.choices[0].message.content
        except Exception as e:
            logger.warning(f"Groq {model} failed: {e}")
    raise ValueError("All Groq models failed")

async def generate_with_deepseek(contents: str, discipline: str, discipline_key: str = None) -> str:
    client = llm_clients.deepseek_client
    if not client:
        raise ValueError(f"DeepSeek client not initialized: {llm_clients.init_errors.get('deepseek', 'unknown')}")
    system_prompt = get_discipline_prompt(discipline, discipline_key)
    response = await client.chat.completions.create(
        model=llm_clients.DEEPSEEK_MODEL,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": contents}],
        max_completion_tokens=2000, temperature=0.2, timeout=30.0
    )
    return response.choices[0].message.content

async def generate_with_sambanova(contents: str, discipline: str, discipline_key: str = None) -> str:
    client = llm_clients.sambanova_client
    if not client:
        raise ValueError(f"SambaNova client not initialized: {llm_clients.init_errors.get('sambanova', 'unknown')}")
    system_prompt = get_discipline_prompt(discipline, discipline_key)
    response = await client.chat.completions.create(
        model=llm_clients.SAMBANOVA_MODEL,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": contents}],
        max_tokens=2000, temperature=0.2, timeout=30.0
    )
    return response.choices[0].message.content

_llm_call_counter = itertools.count()

async def generate_content_with_metadata(contents: str, discipline: str, discipline_key: str = None) -> dict:
    handlers = {"google": generate_with_google, "groq": generate_with_groq, "deepseek": generate_with_deepseek, "sambanova": generate_with_sambanova}
    last_err = None
    idx = next(_llm_call_counter) % len(LLM_FALLBACK_ORDER)
    rotated = LLM_FALLBACK_ORDER[idx:] + LLM_FALLBACK_ORDER[:idx]
    for provider in rotated:
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

async def resolve_match_validation(team1: str, team2: str, date_text: str, disc: str, disc_key: str = None) -> tuple[dict, str, bool, list]:
    """Returns (match_data, report, is_valid, validated_sources)."""
    match_text = f"{team1} vs {team2}"
    val = await validate_match_request(match_text, date_text, disc_key or disc)
    validated_sources = []
    for pr in val.get("participant_reports", []):
        validated_sources.extend(pr.get("validated_sources", []))

    if val.get("status") == "validated" and val.get("match"):
        match_payload = val["match"]
        if val.get("region"): match_payload["region"] = val["region"]
        return match_payload, val.get("report", ""), True, validated_sources
    
    event = await search_event_thesportsdb(match_text)
    if event:
        return {"sport": disc_key or disc, "home": event.get("strHomeTeam", team1), "away": event.get("strAwayTeam", team2), "date": event.get("dateEvent", date_text), "league": event.get("strLeague", ""), "user_discipline": disc}, "TheSportsDB: найден", True, validated_sources
    
    return create_fallback_match_data(match_text, date_text, disc), val.get("report", ""), False, validated_sources

# --- HANDLERS ---
@dp.message(Command("premium"))
async def premium(message: types.Message):
    if not ENABLE_PAYWALL:
        await message.answer("⚙️ Раздел в разработке")
        return
    from services.payment_service import get_payment_info
    info = get_payment_info()
    lines = ["👑 **Подписка SPOTR Premium**\n"]
    if info["rub_price"]:
        lines.append(f"💳 Цена: {info['rub_price']} ₽ / {info['days']} дней")
        if info["rub_details"]:
            lines.append(f"Реквизиты: `{info['rub_details']}`")
    if info["usdt_price"]:
        lines.append(f"💰 USDT: {info['usdt_price']}$ / {info['days']} дней")
        lines.append(f"Сети: {', '.join(info['networks'])}")
        if info["usdt_wallets"]:
            lines.append(f"Кошелёк: `{info['usdt_wallets']}`")
    if not info["rub_price"] and not info["usdt_price"]:
        lines.append("⚙️ Тарифы ещё не настроены. Ожидайте обновлений!")
    lines.append("\n🎟 Есть промокод? /promo")
    await message.answer("\n".join(lines), parse_mode="Markdown")

@dp.message(Command("promo"))
async def promo_command(message: types.Message):
    if not ENABLE_PAYWALL:
        await message.answer("⚙️ Раздел в разработке")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Введите промокод: /promo <код>")
        return
    code = args[1].strip()
    from services.user_store import activate_promo
    result = await activate_promo(message.from_user.id, code)
    await message.answer(f"{'✅' if result['ok'] else '❌'} {result['message']}")

@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()

    await touch_user(message.from_user, admin_telegram_id=ADMIN_TELEGRAM_ID, increment_requests=False)
    kb = []
    if ENABLE_PAYWALL:
        kb.append([types.KeyboardButton(text="🎁 Промо (free)"), types.KeyboardButton(text="⭐ Премиум")])
    kb.extend([[types.KeyboardButton(text="киберспорт"), types.KeyboardButton(text="Футбол")], [types.KeyboardButton(text="Теннис"), types.KeyboardButton(text="ММА/Бокс")], [types.KeyboardButton(text="Волейбол"), types.KeyboardButton(text="Хоккей")], [types.KeyboardButton(text="Баскетбол")]])
    await message.answer("🎯 Выберите дисциплину:", reply_markup=types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True))
    await state.set_state(OrderAnalysis.waiting_discipline)

@dp.message(lambda m: m.text == "🎁 Промо (free)")
async def promo_button(message: types.Message):
    if not ENABLE_PAYWALL:
        return
    user_id = message.from_user.id
    remaining = MAX_FREE_REQUESTS
    if not await check_daily_limit(user_id, max_free=MAX_FREE_REQUESTS):
        remaining = 0
    await message.answer(f"🎁 Бесплатный тариф: {remaining} из {MAX_FREE_REQUESTS} запросов в сутки.\nПросто выберите дисциплину и начните анализ!")

@dp.message(lambda m: m.text == "⭐ Премиум")
async def premium_button(message: types.Message):
    if not ENABLE_PAYWALL:
        return
    await premium(message)

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
    raw = _sanitize_user_input(message.text)
    if not raw:
        await message.answer("❌ Название слишком длинное или содержит недопустимые символы. Попробуйте ещё.")
        return
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
    raw = _sanitize_user_input(message.text)
    if not raw:
        await message.answer("❌ Название слишком длинное или содержит недопустимые символы. Попробуйте ещё.")
        return
    t2_res = resolve_entity_name(raw, discipline=disc)
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
    found, report, valid, validated_sources = await resolve_match_validation(data['team1'], data['team2'], date, data.get('full_discipline', data['discipline']), data.get('discipline_key'))
    if found:
        await state.update_data(found_match=found, clarification_type='ok' if valid else 'fallback', match_validation_report=report, match_validation_sources=validated_sources)
        await callback.message.answer(format_match_confirmation({"status": "ok", "match": found, "needs_confirmation": False}) if valid else f"📊 Анализ: {found['home']} vs {found['away']}")
        await start_analysis(callback.message, state, user_id=callback.from_user.id, real_user=callback.from_user)
    else:
        logger.error("resolve_match_validation returned empty — should never happen")
        await callback.message.answer("❌ Ошибка. Введите первую команду заново:")
        await state.set_state(OrderAnalysis.waiting_team1)

async def fetch_match_data(match_name: str, disc: str, ctx: dict, block: str) -> tuple[str, str]:
    try:
        data = await asyncio.wait_for(get_match_data(match_name, disc, match_context=ctx), timeout=120)
    except Exception:
        data = f"Матч: {match_name}\nДата: {ctx.get('date')}\nСбор данных затянулся. Используй доступное."
    payload = f"{data}\n\n{block}\n\n{build_annotation_block(match_name)}"
    return payload, data

async def _run_analysis(message: types.Message, user_id: int, data: dict, status_msg):
    """Background coroutine that performs the heavy analysis work."""
    try:
        disc = data.get('full_discipline') or data.get('discipline', 'киберспорт')
        m = data.get('found_match') or {}
        if m.get('home') and m.get('away'):
            match_name = f"{m['home']} vs {m['away']}"
        else:
            match_name = data.get('match', 'Unknown vs Unknown')
        ctx = {"date": m.get("date") or data.get("date") or "не указана", "league": m.get("league", ""), "sport": m.get("sport", ""), "home": m.get("home", ""), "away": m.get("away", ""), "pre_validated_sources": data.get("match_validation_sources", [])}

        block = f"Матч: {match_name}\nДата: {ctx['date']}\nЛига: {ctx['league']}\n{data.get('match_validation_report', '')}"

        # --- Event phase check ---
        phase = get_event_phase(ctx["date"], disc)
        if is_event_expired(phase):
            await message.answer("⛔ Событие завершено более 24ч назад, анализ неактуален.")
            return
        if phase is EventPhase.FINISHED:
            cache_key = analysis_cache_key(disc, match_name, ctx["date"])
            cached_res = get_cached_analysis(cache_key, phase=phase)
            if cached_res and cached_res.get("text"):
                final = format_prediction_response(match_name, cached_res["text"])
                for part in split_long_message(f"⚠️ Событие завершено. Последний доступный анализ:\n\n{final}"):
                    await message.answer(part, parse_mode="HTML")
            else:
                await message.answer("⚠️ Событие завершено. Данные устарели, уточните запрос.")
            return

        # --- LLM cache check ---
        cache_key = analysis_cache_key(disc, match_name, ctx["date"])
        cached_res = get_cached_analysis(cache_key, phase=phase)
        if cached_res:
            logger.info("Analysis cache HIT for %s", match_name)
            res = cached_res
        else:
            payload, _ = await fetch_match_data(match_name, disc, ctx, block)
            full_prompt = payload
            res = await generate_content_with_metadata(full_prompt, disc, data.get('discipline_key'))
            if res.get("text"):
                put_cached_analysis(cache_key, res)

        if res.get("text"):
            await record_analysis_result(user_id, discipline=disc, match_text=match_name, success=True)
            final = format_prediction_response(match_name, res["text"])
            for part in split_long_message(final):
                await message.answer(part, parse_mode="HTML")
        else:
            await message.answer("⚠️ Нет ответа")
    except asyncio.TimeoutError:
        logger.warning("Analysis timeout for user %s", user_id)
        await message.answer("⏱️ Анализ превысил максимальное время. Попробуйте позже.")
    except Exception as e:
        logger.exception("Analysis error for user %s: %s", user_id, e)
        await message.answer("❌ Ошибка при анализе.")
    finally:
        try:
            await status_msg.delete()
        except Exception:
            pass


async def start_analysis(message: types.Message, state: FSMContext, *, user_id: int = None, real_user: types.User = None):
    user_id = user_id or message.from_user.id
    
    if ENABLE_PAYWALL:
        if not await check_daily_limit(user_id, max_free=MAX_FREE_REQUESTS):
            await message.answer("❌ Суточный лимит бесплатных прогнозов исчерпан. Попробуйте завтра или ожидайте подписку /premium.")
            await state.clear()
            return
            
    await touch_user(real_user or message.from_user, admin_telegram_id=ADMIN_TELEGRAM_ID, increment_requests=True)
    if ENABLE_PAYWALL:
        await increment_daily_request(user_id)
        
    data = await state.get_data()
    await state.clear()

    # One concurrent analysis per user
    sem = _user_semaphores.setdefault(user_id, asyncio.Semaphore(1))
    if sem.locked():
        await message.answer("⏳ Анализ уже выполняется, подождите.")
        return

    status = await message.answer("🔎 Анализирую...")

    async def _guarded_analysis():
        async with sem:
            await asyncio.wait_for(
                _run_analysis(message, user_id, data, status),
                timeout=_ANALYSIS_TIMEOUT,
            )

    asyncio.create_task(_guarded_analysis())

async def _periodic_cache_cleanup():
    """Hourly cleanup of all in-memory caches."""
    while True:
        await asyncio.sleep(3600)
        try:
            from services.analysis_cache import cleanup_expired_cache as _cleanup_analysis
            from services.data_fetcher import cleanup_expired_cache as _cleanup_data
            from services.external_source import cleanup_team_cache as _cleanup_teams
            from services.match_finder import cleanup_match_cache as _cleanup_matches
            total = _cleanup_analysis() + _cleanup_data() + _cleanup_teams() + _cleanup_matches()
            if total:
                logger.info("Periodic cache cleanup: removed %d entries total", total)
        except Exception as e:
            logger.error("Cache cleanup error: %s", e)


async def main():
    await init_user_store()

    # --- preflight (quiet) ---
    from preflight_check import run_preflight
    status, messages = run_preflight(quiet=True)
    if status == "FAIL":
        for m in messages:
            print(m)
        return
    if status == "WARN":
        for m in messages:
            logger.info(m)

    cleanup_task = None
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        cleanup_task = asyncio.create_task(_periodic_cache_cleanup())
        await dp.start_polling(bot)
    except (Exception,) as e:
        err_name = type(e).__name__
        if "TelegramNetworkError" in err_name or "ClientConnectorError" in err_name:
            print(f"Telegram недоступен: {e}")
        else:
            raise
    finally:
        if cleanup_task:
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass
        await bot.session.close()
        try:
            from services.user_store import close_pool
            await close_pool()
        except Exception:
            pass
        logger.info("Bot shutdown complete")

if __name__ == "__main__":
    asyncio.run(main())
