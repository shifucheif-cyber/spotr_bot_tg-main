import re
import logging

from services.external_source import search_event_thesportsdb
from services.data_fetcher import TennisFetcher

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


def parse_tennis_from_text(match_name: str) -> str:
    match_name = normalize_match_name(match_name)
    players = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s*-\s*", match_name, flags=re.I)
    if len(players) == 2:
        return f"""
Матч: {players[0].strip()} vs {players[1].strip()}

Покрытие: неизвестно (нужно учитывать!)
Усталость: проверить последние матчи за неделю
H2H: важно учитывать личные встречи

Факторы анализа:
- подача и приём
- адаптация к покрытию
- усталость и восстановление
- мотивация и форма

Анализ:
- ATP/WTA Tour и Tennis Explorer помогают проверить статусы на покрытии
- учитывайте, кто лучше играет в роли фаворита/аутсайдера
- подача и приём решают исход на харде и грунте
"""
    return ""


def parse_tennis_fallback(match_name: str) -> str:
    return f"""
Матч: {match_name}

Покрытие: неизвестно
Усталость: проверить форму игроков
H2H: важно учитывать личные встречи

Факторы анализа:
- сервис и возврат
- усталость и плотность расписания
- психологическое состояние

Анализ:
- используйте ATP/WTA и Tennis Explorer для проверки покрытия и формы
- обратите внимание на травмы и дальние перелёты
"""


def fetch_tennis_real_data(match_name: str, match_context: dict | None = None) -> str:
    """Fetch real tennis match data from ATP/WTA and Tennis Explorer."""
    try:
        players = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s*-\s*", match_name, flags=re.I)
        if len(players) != 2:
            return parse_tennis_fallback(match_name)

        player1 = players[0].strip()
        player2 = players[1].strip()
        player1_context = build_context_terms(match_context, player2)
        player2_context = build_context_terms(match_context, player1)
        
        fetcher = TennisFetcher()
        player1_info = fetcher.fetch_player_info(player1, context_terms=player1_context)
        player2_info = fetcher.fetch_player_info(player2, context_terms=player2_context)

        result = f"""
🎾 **Матч:** {player1.upper()} vs {player2.upper()}

**Источники данных:**
- ATP/WTA Tour (официальные рейтинги, статистика на покрытии)
- Tennis Explorer (H2H, анализ по покрытиям, форма)

**Информация об игроке 1 ({player1.upper()}):**
{format_tennis_player_data(player1_info)}

**Информация об игроке 2 ({player2.upper()}):**
{format_tennis_player_data(player2_info)}

**Ключевые метрики:**
- Рейтинг и позиция в рейтинге
- Процент побед на разных покрытиях (хард/грунт/траву)
- Статистика подачи и приёма
- H2H история личных встреч
- Усталость и время последнего матча
- Адаптация к текущему турниру

**Прогноз:**
- Анализируется...
"""
        logger.info(f"Successfully fetched tennis data for {match_name}")
        return result

    except Exception as e:
        logger.error(f"Error fetching tennis real data: {e}")
        return parse_tennis_fallback(match_name)


def format_tennis_player_data(player_info: dict) -> str:
    """Format player information for display."""
    if not player_info:
        return "Данные загружаются..."
    
    lines = []
    for key, value in player_info.items():
        if key not in ["player"] and value:
            if isinstance(value, dict):
                for k, v in value.items():
                    lines.append(f"  - {k}: {v}")
            else:
                lines.append(f"  - {key}: {value}")
    
    return "\n".join(lines) if lines else "Данные загружаются..."


def parse_tennis_external(match_name: str) -> str:
    event = search_event_thesportsdb(match_name)
    if not event:
        return ""

    sport = event.get("strSport", "").lower()
    if sport != "tennis":
        return ""

    return f"""
Матч: {event.get('strHomeTeam', '').strip()} vs {event.get('strAwayTeam', '').strip()}

Турнир: {event.get('strLeague', 'неизвестно')}
Дата: {event.get('dateEvent', 'неизвестно')}
Время: {event.get('strTime', 'неизвестно')}
Покрытие: неизвестно

Факторы анализа:
- подача и приём
- адаптация к покрытию
- усталость и восстановление
- мотивация и форма
"""


def get_tennis_data(match_name: str, subdiscipline: str = "tennis", match_context: dict | None = None) -> str:
    # Выбираем логику в зависимости от дисциплины (большой теннис или настольный)
    if subdiscipline == "table_tennis":
        # Даже если выбран большой теннис, может переключиться на настольный
        from services.table_tennis_service import get_table_tennis_data
        return get_table_tennis_data(match_name, match_context=match_context)
    
    # Try to fetch real data
    result = fetch_tennis_real_data(match_name, match_context=match_context)
    if has_validated_data(result):
        return result

    # Fall back to external sources
    external = parse_tennis_external(match_name)
    if external:
        return external

    result = parse_tennis_from_text(match_name)
    if result:
        return result

    return parse_tennis_fallback(match_name)
