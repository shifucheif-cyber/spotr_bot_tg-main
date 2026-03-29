import re

from services.external_source import search_event_thesportsdb


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
- NBA.com и ESPN помогают проверить травмы и продвинутые метрики
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


def get_basketball_data(match_name: str) -> str:
    external = parse_basketball_external(match_name)
    if external:
        return external

    result = parse_basketball_from_text(match_name)
    if result:
        return result

    return parse_basketball_fallback(match_name)
