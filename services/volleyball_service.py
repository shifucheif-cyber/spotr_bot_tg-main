import re
import logging

from services.external_source import search_event_thesportsdb
from services.data_fetcher import VolleyballFetcher

logger = logging.getLogger(__name__)


def normalize_match_name(match_name: str) -> str:
    return re.sub(r"\s+", " ", match_name.strip())


def parse_volleyball_from_text(match_name: str) -> str:
    match_name = normalize_match_name(match_name)
    teams = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s*-\s*", match_name, flags=re.I)
    if len(teams) == 2:
        return f"""
Матч: {teams[0].strip()} vs {teams[1].strip()}

Факторы:
- связующий и приём
- блок и защита
- домашняя площадка и освещение
- перелёты, jet lag и глубина состава

Анализ:
- WorldofVolley / Volleyball World / Flashscore помогают проверить травмы и форму
- если связующий нестабилен, это сильно влияет на скорость атаки
- плохой приём ухудшает атакующие комбинации
- замены важны при длительной игре и в 4-5 сетах
"""
    return ""


def parse_volleyball_fallback(match_name: str) -> str:
    return f"""
Матч: {match_name}

Факторы:
- связующий и приём
- блок и защита
- домашняя площадка
- перелёты и замены

Анализ:
- оценивайте качество приёма и блокировки
- важна стабильность в атаке и защите
- ищите информацию о связующем и jet lag

"""


def parse_volleyball_external(match_name: str) -> str:
    event = search_event_thesportsdb(match_name)
    if not event or event.get("strSport", "").lower() != "volleyball":
        return ""

    return f"""
Матч: {event.get('strHomeTeam', '').strip()} vs {event.get('strAwayTeam', '').strip()}

Лига: {event.get('strLeague', 'неизвестно')}
Дата: {event.get('dateEvent', 'неизвестно')}
Время: {event.get('strTime', 'неизвестно')}

Факторы:
- связующий и приём
- блок и защита
- домашняя площадка
- замена и глубина состава

Анализ:
- оценивайте качество приёма и блокировки
- важны замены и глубина состава
"""


def fetch_volleyball_real_data(match_name: str) -> str:
    """Fetch real volleyball match data from WorldofVolley and Volleybox."""
    try:
        teams = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s*-\s*", match_name, flags=re.I)
        if len(teams) != 2:
            return f"Матч: {match_name}\n\nДанные загружаются из WorldofVolley и Volleybox..."

        home_team = teams[0].strip()
        away_team = teams[1].strip()
        
        fetcher = VolleyballFetcher()
        home_info = fetcher.fetch_team_info(home_team)
        away_info = fetcher.fetch_team_info(away_team)

        result = f"""
🏐 **Матч:** {home_team.upper()} (H) vs {away_team.upper()} (A)

**Источники данных:**
- WorldofVolley (главный мировой портал волейбола)
- Volleybox (база по игрокам, трансферам, результатам)
- Volleyball World (FIVB - официальные рейтинги)

**Информация о домашней команде ({home_team.upper()}):**
{format_volleyball_data(home_info)}

**Информация о гостевой команде ({away_team.upper()}):**
{format_volleyball_data(away_info)}

**Ключевые метрики:**
- Качество приёма и статистика блока
- Процент побед в разных турнирах
- Глубина состава и замены
- Форма к 4-5 сету (концовка матча)
- Связующий и главные атакующие
- Домашняя/гостевая форма
- Последние матчи (wins/losses)

**Прогноз:**
- Анализируется...
"""
        logger.info(f"Successfully fetched volleyball data for {match_name}")
        return result

    except Exception as e:
        logger.error(f"Error fetching volleyball real data: {e}")
        return f"Матч: {match_name}\n\nДанные загружаются из WorldofVolley и Volleybox..."


def format_volleyball_data(team_info: dict) -> str:
    """Format team information for display."""
    if not team_info:
        return "Данные загружаются..."
    
    lines = []
    for key, value in team_info.items():
        if key not in ["team"] and value:
            if isinstance(value, dict):
                for k, v in value.items():
                    lines.append(f"  - {k}: {v}")
            else:
                lines.append(f"  - {key}: {value}")
    
    return "\n".join(lines) if lines else "Данные загружаются..."


def get_volleyball_data(match_name: str) -> str:
    # Try to fetch real data
    result = fetch_volleyball_real_data(match_name)
    if result and "Данные загружаются из" in result:
        if "не" not in result:
            return result

    # Fall back to external sources
    external = parse_volleyball_external(match_name)
    if external:
        return external

    result = parse_volleyball_from_text(match_name)
    if result:
        return result

    return parse_volleyball_fallback(match_name)
