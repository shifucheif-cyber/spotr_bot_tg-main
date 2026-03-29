import re

from services.external_source import search_event_thesportsdb


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


def get_hockey_data(match_name: str) -> str:
    external = parse_hockey_external(match_name)
    if external:
        return external

    result = parse_hockey_from_text(match_name)
    if result:
        return result

    return parse_hockey_fallback(match_name)
