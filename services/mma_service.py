import re

from services.external_source import search_event_thesportsdb


def normalize_fight_name(fight_name: str) -> str:
    return re.sub(r"\s+", " ", fight_name.strip())


def parse_mma_from_text(fight_name: str) -> str:
    fight_name = normalize_fight_name(fight_name)
    fighters = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s*-\s*", fight_name, flags=re.I)
    if len(fighters) == 2:
        return f"""
Бой: {fighters[0].strip()} vs {fighters[1].strip()}

Факторы:
- рост, размах рук и антропометрия
- силовой стиль, борцовская база, защита
- весогонка, выносливость и восстановление
- последний бой, активность и травмы

Анализ:
- Sherdog / Tapology дают историю боёв и способы побед
- BoxRec помогает проверить рейтинг и активность боксёров
- если борец против ударника, преимущество у борца в клинче
- если есть разница в выносливости, это важно в поздних раундах
"""
    return ""


def parse_mma_fallback(fight_name: str) -> str:
    return f"""
Бой: {fight_name}

Факторы:
- рост и размах рук
- весогонка и подготовка
- стиль и выносливость
- последние результаты

Анализ:
- используйте Sherdog/Tapology и BoxRec для проверки истории и рейтинга
- тренерская подготовка и восстановление после травм важны
"""


def parse_mma_external(fight_name: str) -> str:
    event = search_event_thesportsdb(fight_name)
    if not event:
        return ""

    return f"""
Бой: {event.get('strHomeTeam', '').strip()} vs {event.get('strAwayTeam', '').strip()}

Событие: {event.get('strLeague', 'неизвестно')}
Дата: {event.get('dateEvent', 'неизвестно')}
Время: {event.get('strTime', 'неизвестно')}

Факторы:
- рост и размах рук
- весогонка и подготовка
- последний бой и травмы
- стиль и выносливость

Анализ:
- учитывайте стиль и состояние бойцов
- разница в выносливости важна в поздних раундах
"""


def get_mma_data(fight_name: str) -> str:
    external = parse_mma_external(fight_name)
    if external:
        return external

    result = parse_mma_from_text(fight_name)
    if result:
        return result

    return parse_mma_fallback(fight_name)
