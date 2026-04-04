import asyncio

from services.cs2_service import get_esports_data
from services.football_service import get_football_data
from services.hockey_service import get_hockey_data
from services.tennis_service import get_tennis_data
from services.table_tennis_service import get_table_tennis_data
from services.mma_service import get_mma_data
from services.volleyball_service import get_volleyball_data
from services.basketball_service import get_basketball_data


# Маршруты: (ключевое слово -> (функция, kwargs))
# Порядок важен: более специфичные ключи проверяются первыми
_ROUTES = [
    # Настольный теннис (до обычного тенниса!)
    ("настольный",    lambda m, mc: get_table_tennis_data(m, match_context=mc)),
    ("table_tennis",  lambda m, mc: get_table_tennis_data(m, match_context=mc)),
    ("table",         lambda m, mc: get_table_tennis_data(m, match_context=mc)),
    # Киберспорт
    ("киберспорт",    None),  # placeholder — handled with discipline passthrough
    ("cs2",           None),
    ("cs:",           None),
    ("dota",          None),
    ("lol",           None),
    ("league",        None),
    ("valorant",      None),
    # Футбол
    ("футбол",        lambda m, mc: get_football_data(m, match_context=mc)),
    ("football",      lambda m, mc: get_football_data(m, match_context=mc)),
    ("soccer",        lambda m, mc: get_football_data(m, match_context=mc)),
    # Хоккей
    ("хоккей",        lambda m, mc: get_hockey_data(m, match_context=mc)),
    ("hockey",        lambda m, mc: get_hockey_data(m, match_context=mc)),
    # Теннис (большой)
    ("теннис",        lambda m, mc: get_tennis_data(m, match_context=mc)),
    ("tennis",        lambda m, mc: get_tennis_data(m, match_context=mc)),
    # Бокс (до MMA!)
    ("бокс",          lambda m, mc: get_mma_data(m, subdiscipline="boxing", match_context=mc)),
    ("boxing",        lambda m, mc: get_mma_data(m, subdiscipline="boxing", match_context=mc)),
    # MMA
    ("мма",           lambda m, mc: get_mma_data(m, subdiscipline="mma", match_context=mc)),
    ("mma",           lambda m, mc: get_mma_data(m, subdiscipline="mma", match_context=mc)),
    # Волейбол
    ("волейбол",      lambda m, mc: get_volleyball_data(m, match_context=mc)),
    ("volleyball",    lambda m, mc: get_volleyball_data(m, match_context=mc)),
    # Баскетбол
    ("баскетбол",     lambda m, mc: get_basketball_data(m, match_context=mc)),
    ("basketball",    lambda m, mc: get_basketball_data(m, match_context=mc)),
]


def _get_match_data_sync(match, discipline, match_context=None):
    d = discipline.lower()

    for keyword, handler in _ROUTES:
        if keyword in d:
            if handler is None:
                # Киберспорт — передаём discipline для выбора конкретной игры
                return get_esports_data(match, discipline, match_context=match_context)
            return handler(match, match_context)

    return f"Нет данных для {discipline}"


async def get_match_data(match, discipline, match_context=None):
    d = discipline.lower()
    for keyword, handler in _ROUTES:
        if keyword in d:
            if handler is None:
                # Киберспорт — передаём discipline для выбора конкретной игры
                from services.cs2_service import get_esports_data
                return await get_esports_data(match, discipline, match_context=match_context)
            # Если сервис асинхронный — вызываем через await
            res = handler(match, match_context)
            if asyncio.iscoroutine(res):
                return await res
            return res
    return f"Нет данных для {discipline}"