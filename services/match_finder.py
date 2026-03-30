"""
Match finder module: поиск матчей по командам и датам.
Проверяет дисциплину и дату перед началом анализа.
"""

import re
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple

from services.name_normalizer import normalize_entity_name, resolve_match_entities, split_match_text

logger = logging.getLogger(__name__)

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

# Примеры матчей для демонстрации (в реальности это были бы API запросы)
UPCOMING_MATCHES = {
    "cs2": [
        {"home": "FaZe", "away": "Vitality", "date": "2026-03-30", "league": "ESL Pro League"},
        {"home": "Navi", "away": "Spirit", "date": "2026-03-31", "league": "ESL Pro League"},
    ],
    "dota2": [
        {"home": "Team Liquid", "away": "Secret", "date": "2026-03-30", "league": "The International"},
    ],
    "football": [
        {"home": "Manchester United", "away": "Liverpool", "date": "2026-03-30", "league": "Premier League"},
        {"home": "Real Madrid", "away": "Barcelona", "date": "2026-03-31", "league": "La Liga"},
    ],
    "hockey": [
        {"home": "Toronto Maple Leafs", "away": "Montreal Canadiens", "date": "2026-03-30", "league": "NHL"},
    ],
    "basketball": [
        {"home": "Lakers", "away": "Celtics", "date": "2026-03-30", "league": "NBA"},
    ],
    "tennis": [
        {"home": "Djokovic", "away": "Alcaraz", "date": "2026-03-30", "league": "ATP"},
    ],
    "volleyball": [
        {"home": "Zenit", "away": "Kazan", "date": "2026-03-30", "league": "CEV Champions League"},
    ],
    "mma": [
        {"home": "Volkanovski", "away": "Topuria", "date": "2026-03-30", "league": "UFC"},
    ],
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
    
    # Специальные значения
    if date_str in ["сегодня", "today", "сегодня", "now"]:
        return datetime.now()
    if date_str in ["завтра", "tomorrow", "завтра"]:
        return datetime.now() + timedelta(days=1)
    if date_str in ["послезавтра", "day after tomorrow"]:
        return datetime.now() + timedelta(days=2)
    
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
        "%d.%m",
        "%d/%m/%Y",
        "%d %m %Y",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    
    return None


def normalize_discipline(discipline: str) -> str:
    """Приводит дисциплину к нормализованной форме"""
    d = discipline.lower()
    for main_disc, keywords in DISCIPLINE_MAPPINGS.items():
        if any(kw in d for kw in keywords):
            return main_disc
    return discipline


def get_sport_keys_for_discipline(discipline: str) -> list:
    """Возвращает ключи в UPCOMING_MATCHES для указанной дисциплины"""
    normalized = normalize_discipline(discipline)
    if normalized in DISCIPLINE_MAPPINGS:
        return DISCIPLINE_MAPPINGS[normalized]
    return []


def get_discipline_for_sport(sport_key: str) -> str:
    """Возвращает полное название дисциплины для ключа спорта (например, 'cs2' -> 'киберспорт')"""
    for discipline, keys in DISCIPLINE_MAPPINGS.items():
        if sport_key in keys:
            return discipline
    return sport_key


def find_matches_by_teams(
    team1: Optional[str],
    team2: Optional[str],
    target_date: Optional[datetime] = None,
    discipline: Optional[str] = None,
    days_range: int = 3
) -> list:
    """
    Ищет матч по командам на дату запроса или в близлежащие дни.
    
    Args:
        team1: Первая команда (может быть None)
        team2: Вторая команда (может быть None)
        target_date: Целевая дата поиска
        discipline: Дисциплина (фильтр)
        days_range: Диапазон дней для поиска (+/- дней)
    
    Returns:
        Список найденных матчей с информацией о дисциплине и дате
    """
    
    if not target_date:
        target_date = datetime.now()
    
    # Нормализуем названия команд
    resolved = resolve_match_entities(team1 or "", team2 or "", discipline=discipline)
    team1_value = resolved["team1"]["corrected"] if team1 else None
    team2_value = resolved["team2"]["corrected"] if team2 else None
    team1_norm = normalize_team_name(team1_value) if team1_value else None
    team2_norm = normalize_team_name(team2_value) if team2_value else None
    
    # Если указана дисциплина, получаем соответствующие ключи спорта
    sport_keys = get_sport_keys_for_discipline(discipline) if discipline else None
    
    found_matches = []
    date_range = [target_date + timedelta(days=i) for i in range(-days_range, days_range + 1)]
    date_range_str = [d.strftime("%Y-%m-%d") for d in date_range]
    
    # Ищем во всех дисциплинах
    for sport, matches in UPCOMING_MATCHES.items():
        # Если указана дисциплина, проверяем, находится ли sport в списке ключей
        if sport_keys and sport not in sport_keys:
            continue
        
        for match in matches:
            home_norm = normalize_team_name(match["home"])
            away_norm = normalize_team_name(match["away"])
            match_date = match["date"]
            
            # Проверяем совпадение команд
            team_match = False
            if team1_norm and team2_norm:
                # Обе команды должны совпасть
                if (team1_norm == home_norm and team2_norm == away_norm) or \
                   (team1_norm == away_norm and team2_norm == home_norm):
                    team_match = True
            elif team1_norm:
                # Хотя бы одна из команд совпадает
                if team1_norm in [home_norm, away_norm]:
                    team_match = True
            elif team2_norm:
                if team2_norm in [home_norm, away_norm]:
                    team_match = True
            
            # Проверяем дату
            if team_match and match_date in date_range_str:
                found_matches.append({
                    "sport": sport,
                    "home": match["home"],
                    "away": match["away"],
                    "date": match_date,
                    "league": match["league"],
                    "user_discipline": discipline,
                })
    
    return found_matches


def check_match_clarification(
    match_text: str,
    date_text: str,
    user_discipline: str,
) -> Optional[Dict]:
    """
    Проверяет, нужны ли уточнения перед анализом.
    Возвращает информацию об уточнении или None, если всё в порядке.
    
    Args:
        match_text: Текст матча (например, "FaZe vs Vitality")
        date_text: Текст даты
        user_discipline: Указанная пользователем дисциплина
    
    Returns:
        Dict с уточнениями или None
    """
    
    team1, team2 = parse_match_teams(match_text)
    target_date = parse_date(date_text)
    
    # Ищем матчи
    matches = find_matches_by_teams(
        team1=team1,
        team2=team2,
        target_date=target_date,
        discipline=user_discipline,
        days_range=3
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
            f"✅ **Матч подтвержден:**\n"
            f"🎮 **Дисциплина:** {match['sport']}\n"
            f"🏆 **{match['home']}** vs **{match['away']}**\n"
            f"📅 **Дата:** {match['date']}\n"
            f"🏅 **Лига:** {match['league']}\n\n"
            f"Начинаю анализ..."
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
