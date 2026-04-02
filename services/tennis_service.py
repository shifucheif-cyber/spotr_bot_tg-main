import logging
from services.data_fetcher import TennisFetcher, fetch_match_analysis_data

logger = logging.getLogger(__name__)


def get_tennis_data(match_name: str, subdiscipline: str = "tennis", match_context: dict | None = None) -> str:
    if subdiscipline == "table_tennis":
        from services.table_tennis_service import get_table_tennis_data
        return get_table_tennis_data(match_name, match_context=match_context)
    return fetch_match_analysis_data(
        match_name, TennisFetcher(), "fetch_player_info", "🎾",
        match_context=match_context,
    )
