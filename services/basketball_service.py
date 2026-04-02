import logging
from services.data_fetcher import BasketballFetcher, fetch_match_analysis_data

logger = logging.getLogger(__name__)


def get_basketball_data(match_name: str, match_context: dict | None = None) -> str:
    return fetch_match_analysis_data(
        match_name, BasketballFetcher(), "fetch_team_info", "🏀",
        match_context=match_context,
    )
