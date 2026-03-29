import re

from services.external_source import search_event_thesportsdb


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


def get_table_tennis_data(match_name: str) -> str:
    external = parse_table_tennis_external(match_name)
    if external:
        return external

    result = parse_table_tennis_from_text(match_name)
    if result:
        return result

    return parse_table_tennis_fallback(match_name)
