"""
Match finder module: поиск матчей по командам и датам.
Проверяет дисциплину и дату перед началом анализа.
"""

import re
import hashlib
import logging
import threading
import pytz
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Tuple

from services.name_normalizer import normalize_entity_name, resolve_match_entities, split_match_text
from services.external_source import search_upcoming_events_by_team

logger = logging.getLogger(__name__)

MSK_TZ = pytz.timezone('Europe/Moscow')

# ── Match clarification cache ──
_match_clarif_cache: dict[str, dict] = {}
_MATCH_CACHE_TTL = timedelta(hours=48)
_match_cache_lock = threading.Lock()

def get_msk_now() -> datetime:
    """Возвращает текущее время по Москве."""
    return datetime.now(MSK_TZ)

# Маппинг названий дисциплин
DISCIPLINE_MAPPINGS = {
    "киберспорт": ["cs2", "dota2", "dota", "lol", "valorant", "esports"],
    "футбол": ["football", "soccer", "футбол"],
    "хоккей": ["hockey", "nhl", "хоккей"],
    "баскетбол": ["basketball", "nba", "euroleague", "баскетбол"],
    "теннис": ["tennis", "atp", "wta", "теннис"],
    "настольный теннис": ["table tennis", "ping pong", "tt", "настольный"],
    "мма/бокс": ["mma", "ufc", "boxing", "box", "мма", "бокс"],
    "волейбол": ["volleyball", "вол", "волейбол"],
}


def normalize_team_name(name: str) -> str:
    """Нормализует названия команд для сравнения"""
    return normalize_entity_name(name)


def parse_match_teams(match_text: str) -> Tuple[Optional[str], Optional[str]]:
    """Парсит два названия команд из строки"""
    parts = split_match_text(match_text)
    if len(parts) >= 2:
        return parts[0].strip(), parts[1].strip()
    elif len(parts) == 1:
        return parts[0].strip(), None
    return None, None


def parse_date(date_str: str) -> Optional[datetime]:
    """Парсит дату из строки (поддерживает русские месяцы и разные форматы)"""
    date_str = date_str.strip().lower()
    
    # Инициализируем текущую дату по Москве (без времени для удобства сравнения)
    now_msk = get_msk_now()
    
    # Специальные значения
    if date_str in ["сегодня", "today", "now"]:
        return now_msk
    if date_str in ["завтра", "tomorrow"]:
        return now_msk + timedelta(days=1)
    if date_str in ["послезавтра", "day after tomorrow"]:
        return now_msk + timedelta(days=2)
    
    # Маппинг русских месяцев
    months_map = {
        "января": "01", "февраля": "02", "марта": "03", "апреля": "04",
        "мая": "05", "июня": "06", "июля": "07", "августа": "08",
        "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12",
        "янв": "01", "фев": "02", "мар": "03", "апр": "04",
        "май": "05", "июн": "06", "июл": "07", "авг": "08",
        "сен": "09", "окт": "10", "ноя": "11", "дек": "12",
    }
    
    # Попытка парсить русский формат "30 марта 2026"
    for month_name, month_num in months_map.items():
        if month_name in date_str:
            # Заменяем русский месяц на номер
            date_str_replaced = date_str.replace(month_name, month_num)
            # Пытаемся парсить с разными форматами
            for fmt in ["%d %m %Y", "%d %m %y"]:
                try:
                    return datetime.strptime(date_str_replaced, fmt)
                except ValueError:
                    continue
            break
    
    # Стандартные форматы
    formats = [
        "%d.%m.%Y",
        "%d.%m.%y",  # ✅ Добавляем 2-значный год (30.03.26)
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d %m %Y",
    ]
    
    for fmt in formats:
        try:
            result = datetime.strptime(date_str, fmt)
            return result
        except ValueError:
            continue
    
    # dd.mm без года — парсим вручную, чтобы избежать DeprecationWarning (Python 3.15)
    import re as _re
    m = _re.match(r'^(\d{1,2})\.(\d{1,2})$', date_str)
    if m:
        try:
            return datetime(get_msk_now().year, int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    
    return None


def normalize_discipline(discipline: str) -> str:
    """Приводит дисциплину к нормализованной форме"""
    d = discipline.lower()
    for main_disc, keywords in DISCIPLINE_MAPPINGS.items():
        if any(kw in d for kw in keywords):
            return main_disc
    return discipline


def get_discipline_for_sport(sport_key: str) -> str:
    """Возвращает полное название дисциплины для ключа спорта (например, 'cs2' -> 'киберспорт')"""
    for discipline, keys in DISCIPLINE_MAPPINGS.items():
        if sport_key in keys:
            return discipline
    return sport_key


async def find_matches_by_teams(
    team1: Optional[str],
    team2: Optional[str],
    target_date: Optional[datetime] = None,
    discipline: Optional[str] = None,
    days_range: int = 7
) -> list:
    """
    Ищет матч по командам на дату запроса или в близлежащие дни.
    Использует TheSportsDB API для поиска ближайших матчей.
    """
    if not team1:
        return []
    try:
        matches = await search_upcoming_events_by_team(
            team_name=team1,
            opponent_name=team2,
            target_date=target_date,
            days_range=days_range,
        )
        return matches
    except Exception as e:
        logger.debug("find_matches_by_teams error: %s", e)
        return []


async def check_match_clarification(
    match_text: str,
    date_text: str,
    user_discipline: str,
) -> Optional[Dict]:
    """
    Проверяет, нужны ли уточнения перед анализом. Результаты кэшируются (48ч).
    """
    # Cache lookup
    raw_key = f"{match_text.strip().lower()}|{date_text.strip().lower()}|{user_discipline.strip().lower()}"
    cache_key = hashlib.md5(raw_key.encode()).hexdigest()
    with _match_cache_lock:
        entry = _match_clarif_cache.get(cache_key)
        if entry is not None:
            if datetime.now(tz=timezone.utc) - entry["ts"] <= _MATCH_CACHE_TTL:
                return entry["result"]
            del _match_clarif_cache[cache_key]

    result = await _check_match_clarification_impl(match_text, date_text, user_discipline)

    with _match_cache_lock:
        _match_clarif_cache[cache_key] = {"result": result, "ts": datetime.now(tz=timezone.utc)}
    return result


def cleanup_match_cache() -> int:
    """Remove expired match clarification cache entries. Returns count removed."""
    with _match_cache_lock:
        now = datetime.now(tz=timezone.utc)
        expired = [k for k, v in _match_clarif_cache.items() if now - v["ts"] > _MATCH_CACHE_TTL]
        for k in expired:
            del _match_clarif_cache[k]
        return len(expired)


async def _check_match_clarification_impl(
    match_text: str,
    date_text: str,
    user_discipline: str,
) -> Optional[Dict]:
    """Internal implementation of check_match_clarification (uncached)."""
    
    team1, team2 = parse_match_teams(match_text)
    target_date = parse_date(date_text)
    
    # Ищем матчи
    matches = await find_matches_by_teams(
        team1=team1,
        team2=team2,
        target_date=target_date,
        discipline=user_discipline,
        days_range=7
    )
    
    if not matches:
        logger.warning(f"Матчи не найдены для {match_text} {date_text} ({user_discipline})")
        return None
    
    # Если найден ровно один матч
    if len(matches) == 1:
        match = matches[0]
        actual_sport = match["sport"]  # например, "cs2"
        actual_discipline = get_discipline_for_sport(actual_sport)  # преобразуем в "киберспорт"
        requested_discipline = normalize_discipline(user_discipline)  # преобразуем в "киберспорт"
        
        # Проверяем совпадение дисциплины
        if actual_discipline != requested_discipline:
            return {
                "status": "discipline_mismatch",
                "message": f"⚠️ **Внимание:** матч найден в дисциплине '{actual_discipline.upper()}', а не '{requested_discipline.upper()}'",
                "match": match,
                "needs_confirmation": True,
            }
        
        # Проверяем совпадение даты
        if target_date:
            actual_date = datetime.strptime(match["date"], "%Y-%m-%d")
            if actual_date.date() != target_date.date():
                days_diff = (actual_date.date() - target_date.date()).days
                return {
                    "status": "date_mismatch",
                    "message": f"⚠️ **Внимание:** матч найден на {match['date']} (за {abs(days_diff)} {'день' if abs(days_diff) == 1 else 'дней' if abs(days_diff) < 5 else 'дней'})",
                    "match": match,
                    "needs_confirmation": True,
                }
        
        # Всё совпадает
        return {
            "status": "ok",
            "match": match,
            "needs_confirmation": False,
        }
    
    # Если найдено несколько матчей
    if len(matches) > 1:
        return {
            "status": "multiple_matches",
            "message": f"🔍 **Найдено {len(matches)} матчей:**",
            "matches": matches,
            "needs_confirmation": True,
        }
    
    return None


def format_match_confirmation(clarification: Dict) -> str:
    """Форматирует сообщение об уточнении для пользователя"""
    
    if clarification["status"] == "ok":
        match = clarification["match"]
        return (
            f"✅ **Участники и дисциплина подтверждены:**\n"
            f"🎮 **Дисциплина:** {match['sport']}\n"
            f"🏆 **{match['home']}** vs **{match['away']}**\n"
            f"📅 **Дата:** {match['date']}\n"
            f"🏅 **Лига:** {match['league']}\n\n"
            f"Начинаю анализ по данным пользователя и свежим источникам..."
        )
    
    elif clarification["status"] == "discipline_mismatch":
        match = clarification["match"]
        msg = clarification["message"]
        return (
            f"{msg}\n\n"
            f"📊 **Найденный матч:**\n"
            f"🎮 {match['sport']}\n"
            f"🏆 {match['home']} vs {match['away']}\n"
            f"📅 {match['date']}\n"
            f"🏅 {match['league']}\n\n"
            f"Продолжить анализ этого матча? (Да/Нет)"
        )
    
    elif clarification["status"] == "date_mismatch":
        match = clarification["match"]
        msg = clarification["message"]
        return (
            f"{msg}\n\n"
            f"📊 **Найденный матч:**\n"
            f"🏆 {match['home']} vs {match['away']}\n"
            f"🎮 {match['sport']}\n"
            f"📅 {match['date']}\n"
            f"🏅 {match['league']}\n\n"
            f"Продолжить анализ этого матча? (Да/Нет)"
        )
    
    elif clarification["status"] == "multiple_matches":
        msg = clarification["message"]
        matches_text = ""
        for i, match in enumerate(clarification["matches"], 1):
            matches_text += (
                f"\n{i}. {match['home']} vs {match['away']}\n"
                f"   🎮 {match['sport']} | 📅 {match['date']} | 🏅 {match['league']}"
            )
        
        return msg + matches_text + "\n\nВыберите номер матча или укажите ещё точнее"
    
    return "Уточнение матча..."


def create_fallback_match_data(match_text: str, date_text: str, discipline: str) -> Dict:
    """
    Создает fallback данные для матча, когда точное совпадение не найдено.
    Используется для анализа матчей, которые не в демо-базе.
    """
    team1, team2 = parse_match_teams(match_text)
    target_date = parse_date(date_text)
    
    if not team1 or not team2:
        return None

    resolved = resolve_match_entities(team1, team2, discipline=discipline)
    team1 = resolved["team1"]["corrected"]
    team2 = resolved["team2"]["corrected"]
    
    date_str = target_date.strftime("%Y-%m-%d") if target_date else "дата не указана"
    
    return {
        "sport": "unknown",
        "home": team1,
        "away": team2,
        "date": date_str,
        "league": "User Query",
        "user_discipline": discipline,
    }
