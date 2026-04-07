import logging
from services.data_fetcher import CS2Fetcher, EsportsGameFetcher, fetch_match_analysis_data

logger = logging.getLogger(__name__)

_ESPORTS_CONFIG = {
    "cs2": {"fetcher_fn": CS2Fetcher, "method": "fetch_team_stats", "emoji": "🔫"},
    "dota2": {"fetcher_fn": lambda: EsportsGameFetcher("dota2"), "method": "fetch_team_info", "emoji": "⚔️"},
    "lol": {"fetcher_fn": lambda: EsportsGameFetcher("lol"), "method": "fetch_team_info", "emoji": "🎮"},
    "valorant": {"fetcher_fn": lambda: EsportsGameFetcher("valorant"), "method": "fetch_team_info", "emoji": "🎯"},
}


def _resolve_game_key(discipline: str) -> str | None:
    d = discipline.lower()
    if "cs" in d or "counter-strike" in d:
        return "cs2"
    if "dota" in d:
        return "dota2"
    if "lol" in d or "league" in d:
        return "lol"
    if "valorant" in d:
        return "valorant"
    return None


async def get_esports_data(match_name: str, discipline: str, match_context: dict | None = None) -> str:
    game_key = _resolve_game_key(discipline)
    if not game_key or game_key not in _ESPORTS_CONFIG:
        return f"Матч: {match_name}\n\nНеизвестная киберспортивная дисциплина: {discipline}"
    config = _ESPORTS_CONFIG[game_key]
    fetcher = config["fetcher_fn"]()
    return await fetch_match_analysis_data(
        match_name, fetcher, config["method"], config["emoji"],
        match_context=match_context,
    )
