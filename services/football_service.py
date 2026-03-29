import re
import logging

from services.external_source import search_event_thesportsdb
from services.data_fetcher import FootballFetcher

logger = logging.getLogger(__name__)


def normalize_match_name(match_name: str) -> str:
    return re.sub(r"\s+", " ", match_name.strip())


def parse_football_from_text(match_name: str) -> str:
    match_name = normalize_match_name(match_name)
    teams = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s*-\s*", match_name, flags=re.I)
    if len(teams) == 2:
        return f"""
Матч: {teams[0].strip()} vs {teams[1].strip()}

Факторы:
- домашнее поле и прогнозируемый состав
- травмы, дисквалификации и ротация состава
- последние результаты и мотивация
- стиль игры, тактика и погодные условия

Анализ:
- WhoScored/SofaScore помогают оценить влияние травм и настроения игроков
- Transfermarkt показывает, насколько активен клуб на трансферном рынке
- Flashscore важен для оценки формы и H2H
- если домашняя команда играет стабильнее, это сильный плюс
"""
    return ""


def parse_football_fallback(match_name: str) -> str:
    return f"""
Матч: {match_name}

Факторы:
- домашнее/выездное положение
- состав и травмы
- тактика и мотивация
- последние результаты

Анализ:
- анализируйте прогнозы состава и травменный лист
- учитывайте, как команда выдержит интенсивный график
- используйте данные с WhoScored/SofaScore и Flashscore для оценки формы
"""


def fetch_football_real_data(match_name: str) -> str:
    """
    Fetch real football match data from WhoScored, SofaScore, Transfermarkt.
    
    Args:
        match_name: Match name (e.g., "Manchester United vs Liverpool")
        
    Returns:
        Structured data with match information
    """
    try:
        teams = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s*-\s*", match_name, flags=re.I)
        if len(teams) != 2:
            logger.warning(f"Could not parse teams from {match_name}")
            return parse_football_fallback(match_name)

        home_team = teams[0].strip()
        away_team = teams[1].strip()
        
        fetcher = FootballFetcher()
        
        # Fetch team info
        home_info = fetcher.fetch_team_info(home_team)
        away_info = fetcher.fetch_team_info(away_team)

        # Format data for LLM analysis
        result = f"""
⚽ **Матч:** {home_team.upper()} (H) vs {away_team.upper()} (A)

**Источники данных:**
- WhoScored (статистика, оценки игроков, тепловые карты)
- SofaScore/Flashscore (травмы, дисквалификации, форма)
- Transfermarkt (вес состава, трансферы)

**Информация о домашней команде ({home_team.upper()}):**
{format_football_team_data(home_info) if home_info else "Загрузка данных..."}

**Информация о гостевой команде ({away_team.upper()}):**
{format_football_team_data(away_info) if away_info else "Загрузка данных..."}

**Ключевые метрики:**
- Винрейт дома/в гостях за последние 5 матчей
- Забито/пропущено в среднем за матч
- Ключевые игроки в стартовом составе
- Состояние вратаря и защиты
- Травменный лист и дисквалификации

**История личных встреч (H2H):**
- Анализируется...

**Прогнозируемые составы:**
- Загружаются с WhoScored...
"""
        
        logger.info(f"Successfully fetched football data for {match_name}")
        return result

    except Exception as e:
        logger.error(f"Error fetching football real data: {e}")
        return parse_football_fallback(match_name)


def format_football_team_data(team_info: dict) -> str:
    """Format team information for display."""
    if not team_info:
        return "Данные загружаются..."
    
    lines = []
    for key, value in team_info.items():
        if key not in ["source"] and value:
            if isinstance(value, dict):
                for k, v in value.items():
                    lines.append(f"  - {k}: {v}")
            else:
                lines.append(f"  - {key}: {value}")
    
    return "\n".join(lines) if lines else "Данные загружаются..."


def parse_football_external(match_name: str) -> str:
    event = search_event_thesportsdb(match_name)
    if not event or event.get("strSport", "").lower() not in {"soccer", "football"}:
        return ""

    return f"""
Матч: {event.get('strHomeTeam', '').strip()} vs {event.get('strAwayTeam', '').strip()}

Лига: {event.get('strLeague', 'неизвестно')}
Дата: {event.get('dateEvent', 'неизвестно')}
Время: {event.get('strTime', 'неизвестно')}
Стадион: {event.get('strVenue', 'неизвестно')}

Факторы:
- Домашнее поле и составы
- Травмы, дисквалификации и ротация
- Последние результаты и мотивация
- Погодные условия и стиль игры

Анализ:
- если домашняя команда играет стабильнее, это сильный плюс
- отсутствие лидеров обороны или атаки меняет расклад
- учитывайте график и мотивацию команд
"""


def get_football_data(match_name: str) -> str:
    # Try to fetch real data from multiple sources
    result = fetch_football_real_data(match_name)
    if result and "Загрузка данных..." not in result:
        return result

    # Fall back to external sources
    external = parse_football_external(match_name)
    if external:
        return external

    # Fall back to template
    result = parse_football_from_text(match_name)
    if result:
        return result

    return parse_football_fallback(match_name)
