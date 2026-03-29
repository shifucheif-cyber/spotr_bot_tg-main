import re

from services.external_source import search_event_thesportsdb


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


def get_tennis_data(match_name: str) -> str:
    external = parse_tennis_external(match_name)
    if external:
        return external

    result = parse_tennis_from_text(match_name)
    if result:
        return result

    return parse_tennis_fallback(match_name)
