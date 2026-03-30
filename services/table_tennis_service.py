import re
import logging

from services.external_source import search_event_thesportsdb
from services.data_fetcher import TableTennisFetcher

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


def parse_table_tennis_from_text(match_name: str) -> str:
    match_name = normalize_match_name(match_name)
    players = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s*-\s*", match_name, flags=re.I)
    if len(players) == 2:
        return f"""
Матч: {players[0].strip()} vs {players[1].strip()}

Факторы:
- скорость, реакция и переходы
- подача и возврат
- стиль игры (атака / контр)
- тактика, восстановление и форма

Анализ:
- TT-Cup / Setka Cup помогают понять, как часто меняется форма
- важно, кто лучше контролирует темп и подачу
- слабый возврат усиливает давление на соперника
"""
    return ""


def parse_table_tennis_external(match_name: str) -> str:
    event = search_event_thesportsdb(match_name)
    if not event:
        return ""

    sport = event.get("strSport", "").lower()
    if sport not in {"table tennis", "настольный теннис"}:
        return ""

    return f"""
Матч: {event.get('strHomeTeam', '').strip()} vs {event.get('strAwayTeam', '').strip()}

Турнир: {event.get('strLeague', 'неизвестно')}
Дата: {event.get('dateEvent', 'неизвестно')}
Время: {event.get('strTime', 'неизвестно')}

Факторы:
- скорость и реакция
- подача и возврат
- стиль игры (атака / контр)
- тактика и устойчивость

Анализ:
- учитывайте, кто лучше контролирует подачу и вращение
- реакция в розыгрышах определяет преимущества
"""


def parse_table_tennis_fallback(match_name: str) -> str:
    return f"""
Матч: {match_name}

Факторы:
- скорость и реакция
- подача и возврат
- стиль игры (атака / контр)
- тактика и устойчивость

Анализ:
- обращайте внимание на скорость и качество подачи
- устойчивость важна в длинных розыгрышах
"""


def fetch_table_tennis_real_data(match_name: str, match_context: dict | None = None) -> str:
    """Fetch real table tennis match data from Flashscore, TT-Cup, Setka Cup."""
    try:
        players = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s*-\s*", match_name, flags=re.I)
        if len(players) != 2:
            return f"Матч: {match_name}\n\nДанные загружаются из Flashscore и Setka Cup..."

        player1 = players[0].strip()
        player2 = players[1].strip()
        player1_context = build_context_terms(match_context, player2)
        player2_context = build_context_terms(match_context, player1)
        
        fetcher = TableTennisFetcher()
        p1_info = fetcher.fetch_player_info(player1, context_terms=player1_context)
        p2_info = fetcher.fetch_player_info(player2, context_terms=player2_context)

        result = f"""
🏓 **Матч:** {player1.upper()} vs {player2.upper()}

**Источники данных:**
- Flashscore (настольный теннис раздел - Лига Про, динамика дня)
- TT-Cup / Setka Cup (последние 10-15 матчей, контроль формы)

**Информация об игроке 1 ({player1.upper()}):**
{format_table_tennis_data(p1_info)}

**Информация об игроке 2 ({player2.upper()}):**
{format_table_tennis_data(p2_info)}

**Ключевые метрики:**
- Скорость реакции и подача
- Стиль игры (атака / контроль / оборона)
- Эффективность розыгрышей
- Недавние результаты (последние 10-15 матчей)
- H2H история личных встреч
- Усталость и график матчей
- Адаптация к стилю противника

**Прогноз:**
- Анализируется...
"""
        logger.info(f"Successfully fetched table tennis data for {match_name}")
        return result

    except Exception as e:
        logger.error(f"Error fetching table tennis real data: {e}")
        return f"Матч: {match_name}\n\nДанные загружаются из Flashscore и Setka Cup..."


def format_table_tennis_data(player_info: dict) -> str:
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


def get_table_tennis_data(match_name: str, match_context: dict | None = None) -> str:
    # Try to fetch real data
    result = fetch_table_tennis_real_data(match_name, match_context=match_context)
    if has_validated_data(result):
        return result

    # Fall back to external sources
    external = parse_table_tennis_external(match_name)
    if external:
        return external

    result = parse_table_tennis_from_text(match_name)
    if result:
        return result

    return parse_table_tennis_fallback(match_name)
