import logging
from services.data_fetcher import MMAFetcher, fetch_match_analysis_data

logger = logging.getLogger(__name__)


def get_mma_data(fight_name: str, subdiscipline: str = "mma", match_context: dict | None = None) -> str:
    emoji = "🥊" if subdiscipline == "boxing" else "🥋"
    return fetch_match_analysis_data(
        fight_name, MMAFetcher(subdiscipline), "fetch_fighter_info", emoji,
        match_context=match_context,
    )
async def get_mma_data(fight_name: str, subdiscipline: str = "mma", match_context: dict | None = None) -> str:
    emoji = "🥊" if subdiscipline == "boxing" else "🥋"
    return await fetch_match_analysis_data(
        fight_name, MMAFetcher(subdiscipline), "fetch_fighter_info", emoji,
        match_context=match_context,
    )
