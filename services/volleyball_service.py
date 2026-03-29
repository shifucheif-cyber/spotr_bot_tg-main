import re

from services.external_source import search_event_thesportsdb


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


def get_volleyball_data(match_name: str) -> str:
    external = parse_volleyball_external(match_name)
    if external:
        return external

    result = parse_volleyball_from_text(match_name)
    if result:
        return result

    return parse_volleyball_fallback(match_name)
