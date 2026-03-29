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

    if "киберспорт" in d or "cs" in d or "dota" in d or "lol" in d or "esport" in d:
        return get_esports_data(match, discipline)

    elif "футбол" in d or "football" in d or "soccer" in d:
        return get_football_data(match)

    elif "хоккей" in d or "hockey" in d:
        return get_hockey_data(match)

    elif "настольный теннис" in d or "table tennis" in d:
        return get_table_tennis_data(match)

    elif "теннис" in d or "tennis" in d:
        return get_tennis_data(match)

    elif "mma" in d or "мма" in d or "бокс" in d or "box" in d:
        return get_mma_data(match)

    elif "волейбол" in d or "volleyball" in d:
        return get_volleyball_data(match)

    elif "баскетбол" in d or "basketball" in d:
        return get_basketball_data(match)

    else:
        return f"Нет данных для {discipline}"