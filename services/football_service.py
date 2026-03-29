import re

from services.external_source import search_event_thesportsdb


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
    external = parse_football_external(match_name)
    if external:
        return external

    result = parse_football_from_text(match_name)
    if result:
        return result

    return parse_football_fallback(match_name)
