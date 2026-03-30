import re
import logging

from services.external_source import search_event_thesportsdb
from services.data_fetcher import BasketballFetcher

logger = logging.getLogger(__name__)


def has_validated_data(result: str) -> bool:
    return bool(result) and "Валидация: validated" in result and "Подтверждено источников:" in result


def build_context_terms(match_context: dict | None, opponent: str) -> str:
    if not match_context:
        return opponent
    parts = [opponent, match_context.get("date", ""), match_context.get("league", "")]
    return " ".join(part for part in parts if part)


def normalize_match_name(match_name: str) -> str:
    return re.sub(r"\s+", " ", match_name.strip())


def parse_basketball_from_text(match_name: str) -> str:
    match_name = normalize_match_name(match_name)
    teams = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s*-\s*", match_name, flags=re.I)
    if len(teams) == 2:
        return f"""
Матч: {teams[0].strip()} vs {teams[1].strip()}

Факторы:
- домашнее поле и темп игры
- защита, подборы и эффективность внутри
- травмы ключевых лидеров
- скамейка, ротация и кондиции

Анализ:
- Basketball-Reference и Euroleague official помогают проверить темп и эффективность
- команда с лучшей защитой и подбором часто доминирует
- скорость игры и качество трёхочковых решают итог
- глубина скамейки важна в концовке
"""
    return ""


def parse_basketball_fallback(match_name: str) -> str:
    return f"""
Матч: {match_name}

Факторы:
- домашнее поле и темп
- защита и подборы
- состав и травмы

Анализ:
- обратите внимание на концовку и ротацию
- учитывайте травмы лидеров и качество скамейки
"""


def fetch_basketball_real_data(match_name: str, match_context: dict | None = None) -> str:
    """Fetch real basketball match data from Basketball-Reference and Euroleague official."""
    try:
        teams = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s*-\s*", match_name, flags=re.I)
        if len(teams) != 2:
            return parse_basketball_fallback(match_name)

        home_team = teams[0].strip()
        away_team = teams[1].strip()
        home_context = build_context_terms(match_context, away_team)
        away_context = build_context_terms(match_context, home_team)
        
        fetcher = BasketballFetcher()
        home_info = fetcher.fetch_team_info(home_team, context_terms=home_context)
        away_info = fetcher.fetch_team_info(away_team, context_terms=away_context)

        result = f"""
🏀 **Матч:** {home_team.upper()} (H) vs {away_team.upper()} (A)

**Источники данных:**
- Basketball-Reference (темп, эффективность, полная NBA база)
- Euroleaguebasketball.net (официальная статистика Евролиги)

**Информация о домашней команде ({home_team.upper()}):**
{format_basketball_data(home_info)}

**Информация о гостевой команде ({away_team.upper()}):**
{format_basketball_data(away_info)}

**Ключевые метрики:**
- Темп игры и эффективность защиты
- Качество подборов и трёхочковых
- Глубина скамейки и ротация
- Последние 5 матчей (wins/losses)
- Травмы ключевых игроков
- Домашняя/гостевая форма

**Прогноз:**
- Анализируется...
"""
        logger.info(f"Successfully fetched basketball data for {match_name}")
        return result

    except Exception as e:
        logger.error(f"Error fetching basketball real data: {e}")
        return parse_basketball_fallback(match_name)


def format_basketball_data(team_info: dict) -> str:
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


def parse_basketball_external(match_name: str) -> str:
    event = search_event_thesportsdb(match_name)
    if not event or event.get("strSport", "").lower() != "basketball":
        return ""

    return f"""
Матч: {event.get('strHomeTeam', '').strip()} vs {event.get('strAwayTeam', '').strip()}

Лига: {event.get('strLeague', 'неизвестно')}
Дата: {event.get('dateEvent', 'неизвестно')}
Время: {event.get('strTime', 'неизвестно')}

Факторы:
- Домашнее поле и темп игры
- Защита и подборы
- Травмы ключевых игроков
- Скамейка и ротация

Анализ:
- команда с лучшей защитой и подбором часто доминирует
- скорость игры и качество трёхочковых решают итог
"""


def get_basketball_data(match_name: str, match_context: dict | None = None) -> str:
    # Try to fetch real data
    result = fetch_basketball_real_data(match_name, match_context=match_context)
    if has_validated_data(result):
        return result

    # Fall back to external sources
    external = parse_basketball_external(match_name)
    if external:
        return external

    result = parse_basketball_from_text(match_name)
    if result:
        return result

    return parse_basketball_fallback(match_name)
