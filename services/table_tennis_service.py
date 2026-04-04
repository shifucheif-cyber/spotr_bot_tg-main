import logging
from services.data_fetcher import TableTennisFetcher, fetch_match_analysis_data

logger = logging.getLogger(__name__)


async def get_table_tennis_data(match_name: str, match_context: dict | None = None) -> str:
    return await fetch_match_analysis_data(
        match_name, TableTennisFetcher(), "fetch_player_info", "🏓",
        match_context=match_context,
    )
