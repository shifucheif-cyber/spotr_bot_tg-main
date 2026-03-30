from services.cs2_service import get_esports_data
from services.football_service import get_football_data
from services.hockey_service import get_hockey_data
from services.tennis_service import get_tennis_data
from services.table_tennis_service import get_table_tennis_data
from services.mma_service import get_mma_data
from services.volleyball_service import get_volleyball_data
from services.basketball_service import get_basketball_data

async def get_match_data(match, discipline):
    d = discipline.lower()

    # КИБЕРСПОРТ - маршрутизация конкретной игры
    if "киберспорт" in d or "cs2" in d or "cs:" in d:
        return get_esports_data(match, discipline)
    elif "dota" in d or "dota2" in d or "dota:" in d:
        return get_esports_data(match, discipline)
    elif "lol" in d or "league" in d or "lol:" in d:
        return get_esports_data(match, discipline)
    elif "valorant" in d or "valorant:" in d:
        return get_esports_data(match, discipline)

    # ФУТБОЛ
    elif "футбол" in d or "football" in d or "soccer" in d:
        return get_football_data(match)

    # ХОККЕЙ
    elif "хоккей" in d or "hockey" in d:
        return get_hockey_data(match)

    # ТЕННИС - большой теннис или настольный
    elif "теннис:" in d and "настольный" in d:
        # Настольный теннис
        return get_table_tennis_data(match)
    elif "table" in d or "настольный" in d or "table_tennis" in d:
        return get_table_tennis_data(match)
    elif "теннис" in d or "tennis" in d:
        # Большой теннис (по умолчанию)
        return get_tennis_data(match)

    # ММА/БОКС - выбор между ММА и Бокс
    elif "ммА:" in d and "бокс" in d:
        # Бокс
        return get_mma_data(match, subdiscipline="boxing")
    elif "boxing" in d or "бокс" in d:
        return get_mma_data(match, subdiscipline="boxing")
    elif "mma" in d or "мма" in d:
        return get_mma_data(match, subdiscipline="mma")

    # ВОЛЕЙБОЛ
    elif "волейбол" in d or "volleyball" in d:
        return get_volleyball_data(match)

    # БАСКЕТБОЛ
    elif "баскетбол" in d or "basketball" in d:
        return get_basketball_data(match)

    else:
        return f"Нет данных для {discipline}"