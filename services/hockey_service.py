import re
import logging

from services.external_source import search_event_thesportsdb
from services.data_fetcher import HockeyFetcher

logger = logging.getLogger(__name__)


def normalize_match_name(match_name: str) -> str:
    return re.sub(r"\s+", " ", match_name.strip())


def parse_hockey_from_text(match_name: str) -> str:
    match_name = normalize_match_name(match_name)
    teams = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s*-\s*", match_name, flags=re.I)
    if len(teams) == 2:
        return f"""
Матч: {teams[0].strip()} vs {teams[1].strip()}

Факторы:
- вратарь и его форма
- спецбригады (большинство / меньшинство)
- лед и домашнее/выездное положение
- травмы и ротации линий

Анализ:
- NHL.com и ESPN помогают проверить травмы и продвинутые метрики
- сильный вратарь и спецбригады часто решают исход
- важно учитывать, кто сильнее играет в компоненте большинства
- ротация линий и переходы критичны в концовке
"""
    return ""


def parse_hockey_fallback(match_name: str) -> str:
    return f"""
Матч: {match_name}

Факторы:
- домашнее/выездное положение
- форма вратаря
- спецбригады и состав
- травмы ключевых игроков

Анализ:
- оцените эффективность большинства и меньшинства
- учитывайте силу нападения и игру в обороне
- используйте источники NHL.com и ESPN для проверки травм
"""


def parse_hockey_external(match_name: str) -> str:
    event = search_event_thesportsdb(match_name)
    if not event or event.get("strSport", "").lower() != "ice hockey":
        return ""

    return f"""
Матч: {event.get('strHomeTeam', '').strip()} vs {event.get('strAwayTeam', '').strip()}

Лига: {event.get('strLeague', 'неизвестно')}
Дата: {event.get('dateEvent', 'неизвестно')}
Время: {event.get('strTime', 'неизвестно')}
Арена: {event.get('strVenue', 'неизвестно')}

Факторы:
- Вратарь и его форма
- Спецбригады (большинство / меньшинство)
- Лед и домашнее/выездное положение
- Травмы и ротации линий

Анализ:
- сильный вратарь и спецбригады часто решают исход
- учитывайте эффективность большинства и меньшинства
- ротация линий критична в концовке
"""


def fetch_hockey_real_data(match_name: str) -> str:
    """Fetch real hockey match data from EliteProspects and NaturalStatTrick."""
    try:
        teams = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s*-\s*", match_name, flags=re.I)
        if len(teams) != 2:
            return f"Матч: {match_name}\n\nДанные загружаются из EliteProspects и NaturalStatTrick..."

        home_team = teams[0].strip()
        away_team = teams[1].strip()
        
        fetcher = HockeyFetcher()
        home_info = fetcher.fetch_team_info(home_team)
        away_info = fetcher.fetch_team_info(away_team)

        result = f"""
🏒 **Матч:** {home_team.upper()} (H) vs {away_team.upper()} (A)

**Источники данных:**
- EliteProspects (статистика игроков и команд)
- NaturalStatTrick (продвинутая статистика НХЛ - xG, Corsi)

**Информация о домашней команде ({home_team.upper()}):**
{format_hockey_data(home_info)}

**Информация о гостевой команде ({away_team.upper()}):**
{format_hockey_data(away_info)}

**Ключевые метрики:**
- Форма вратаря и спецбригад (большинство/меньшинство)
- Corsi (контроль шайбы) и xG (ожидаемые голы)
- Эффективность защиты и атаки
- Травмы ключевых игроков
- Ротация линий и составы
- Домашняя/гостевая форма

**Прогноз:**
- Анализируется...
"""
        logger.info(f"Successfully fetched hockey data for {match_name}")
        return result

    except Exception as e:
        logger.error(f"Error fetching hockey real data: {e}")
        return f"Матч: {match_name}\n\nДанные загружаются из EliteProspects и NaturalStatTrick..."


def format_hockey_data(team_info: dict) -> str:
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


def get_hockey_data(match_name: str) -> str:
    # Try to fetch real data
    result = fetch_hockey_real_data(match_name)
    if result and "Данные загружаются из" in result and "не" not in result:
        if "Данные загружаются..." in result:
            pass  # fallthrough
        else:
            return result

    # Fall back to external sources
    external = parse_hockey_external(match_name)
    if external:
        return external

    result = parse_hockey_from_text(match_name)
    if result:
        return result

    return parse_hockey_fallback(match_name)
