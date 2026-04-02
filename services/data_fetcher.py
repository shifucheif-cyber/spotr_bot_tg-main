"""
Universal data fetching module for match analysis.
Handles verification from multiple sources and data extraction.
"""

import logging
import re
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from urllib.parse import quote

from services.search_engine import (
    collect_validated_sources,
    format_validated_report,
    search_cs2_stats,
    search_dota_stats,
    search_football_stats,
    search_lol_stats,
    search_tennis_player,
    search_table_tennis_player,
    search_mma_fighter,
    search_boxing_fighter,
    search_basketball_team,
    search_hockey_team,
    search_valorant_stats,
    search_volleyball_team
)

logger = logging.getLogger(__name__)

# User agents for requests
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

TIMEOUT = 10


class DataFetcher:
    """Base class for fetching match data from various sources."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def fetch_url(self, url: str) -> Optional[str]:
        """
        Safely fetch URL content.
        
        Args:
            url: URL to fetch
            
        Returns:
            Response text or None on failure
        """
        try:
            response = self.session.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None

    def search_google(self, query: str, language: str = "en") -> List[str]:
        """
        Generate search URLs (not actual Google search, but URL patterns).
        This is a placeholder for actual search implementation.
        
        Args:
            query: Search query
            language: Language code (en, ru)
            
        Returns:
            List of potential URLs to search
        """
        urls = []
        # This would be replaced with actual search API or web scraping
        # For now, returning placeholder URLs based on query
        if "CS2" in query or "counter-strike" in query.lower():
            urls.extend([
                f"https://www.hltv.org/results?event={quote(query)}",
                f"https://liquipedia.net/counterstrike/search?query={quote(query)}"
            ])
        return urls

    def verify_data(self, data_sources: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Verify data from multiple sources and return consolidated result.
        
        Args:
            data_sources: List of data from different sources
            
        Returns:
            Verified consolidated data
        """
        if not data_sources:
            return {}

        # Simple aggregation - can be enhanced with more sophisticated logic
        consolidated = {}
        for source in data_sources:
            for key, value in source.items():
                if key not in consolidated:
                    consolidated[key] = value
                # Could add conflict resolution logic here

        return consolidated

    def build_validated_payload(
        self,
        entity: str,
        discipline: str,
        stat_type: str,
        entity_key: str,
        context_terms: Optional[str] = None,
    ) -> Dict[str, Any]:
        report = collect_validated_sources(
            entity,
            discipline,
            stat_type,
            min_sources=2,
            timelimit="m",
            context_terms=context_terms,
        )
        sources = ", ".join(source["source"] for source in report["validated_sources"]) or "нет"
        return {
            entity_key: entity,
            "status": report["status"],
            "validated_count": report["validated_count"],
            "validated_sources": sources,
            "freshness_window": report["freshness_window"],
            "report": format_validated_report(report),
        }


class CS2Fetcher(DataFetcher):
    """Fetch CS2/Counter-Strike 2 data from multiple sources."""

    def fetch_team_stats(self, team_name: str, context_terms: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Fetch CS2 team statistics from HLTV.
        
        Args:
            team_name: Team name to search
            
        Returns:
            Dictionary with team stats or None
        """
        try:
            logger.info(f"Fetching CS2 validated stats for {team_name}")
            return self.build_validated_payload(
                team_name,
                "cs2",
                "ranking roster maps recent results",
                "team",
                context_terms=context_terms,
            )
        except Exception as e:
            logger.error(f"Error fetching team stats for {team_name}: {e}")
            return None

    def fetch_match_info(self, team1: str, team2: str, context_terms: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Fetch CS2 match information from multiple sources.
        
        Args:
            team1: First team name
            team2: Second team name
            
        Returns:
            Dictionary with match info from multiple sources
        """
        try:
            match_query = f"{team1} vs {team2}"
            logger.info(f"Searching for CS2 match info: {match_query}")

            return self.build_validated_payload(
                f"{team1} vs {team2}",
                "cs2",
                "h2h roster maps recent results",
                "match",
                context_terms=context_terms,
            )
        except Exception as e:
            logger.error(f"Error fetching match info for {team1} vs {team2}: {e}")
            return None


class EsportsGameFetcher(DataFetcher):
    """Fetch Dota 2, LoL, or Valorant data from configured esports sources."""

    GAME_CONFIG = {
        "dota2": {
            "team_stat_type": "hero meta pub stats pro player form recent results",
            "match_stat_type": "stand-ins brackets hero meta recent results",
            "team_search": search_dota_stats,
        },
        "lol": {
            "team_stat_type": "gold per minute objective control draft form recent results",
            "match_stat_type": "draft roster changes objective control recent results",
            "team_search": search_lol_stats,
        },
        "valorant": {
            "team_stat_type": "map stats agent stats lineup recent results",
            "match_stat_type": "map stats agents roster changes recent results",
            "team_search": search_valorant_stats,
        },
    }

    def __init__(self, game_key: str):
        super().__init__()
        if game_key not in self.GAME_CONFIG:
            raise ValueError(f"Unsupported esports game key: {game_key}")
        self.game_key = game_key
        self.config = self.GAME_CONFIG[game_key]

    def fetch_team_info(self, team_name: str, context_terms: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            logger.info("Fetching %s esports info for %s", self.game_key, team_name)
            return self.build_validated_payload(
                team_name,
                self.game_key,
                self.config["team_stat_type"],
                "team",
                context_terms=context_terms,
            )
        except Exception as e:
            logger.error("Error fetching %s team info for %s: %s", self.game_key, team_name, e)
            return None

    def fetch_match_info(self, team1: str, team2: str, context_terms: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            logger.info("Fetching %s match info for %s vs %s", self.game_key, team1, team2)
            return self.build_validated_payload(
                f"{team1} vs {team2}",
                self.game_key,
                self.config["match_stat_type"],
                "match",
                context_terms=context_terms,
            )
        except Exception as e:
            logger.error("Error fetching %s match info for %s vs %s: %s", self.game_key, team1, team2, e)
            return None


class FootballFetcher(DataFetcher):
    """Fetch football data from multiple sources."""

    def fetch_team_info(self, team_name: str, context_terms: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch football team information."""
        try:
            logger.info(f"Fetching football info for {team_name}")
            return self.build_validated_payload(
                team_name,
                "football",
                "injuries lineup xg recent results",
                "team",
                context_terms=context_terms,
            )
        except Exception as e:
            logger.error(f"Error fetching football info for {team_name}: {e}")
            return None


class TennisFetcher(DataFetcher):
    """Fetch tennis data from ATP/WTA and Tennis Explorer."""

    def fetch_player_info(self, player_name: str, context_terms: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch tennis player information."""
        try:
            logger.info(f"Fetching tennis info for {player_name}")
            return self.build_validated_payload(
                player_name,
                "tennis",
                "ranking h2h surface form recent matches",
                "player",
                context_terms=context_terms,
            )
        except Exception as e:
            logger.error(f"Error fetching tennis info for {player_name}: {e}")
            return None


class MMAFetcher(DataFetcher):
    """Fetch MMA/Boxing data from Sherdog, UFC Stats, and BoxRec."""

    def __init__(self, subdiscipline: str = "mma"):
        super().__init__()
        self._discipline = "boxing" if subdiscipline == "boxing" else "mma"
        self._stat_type = (
            "record titles ranking opposition recent fight"
            if self._discipline == "boxing"
            else "record reach striking takedowns recent fight"
        )

    def fetch_fighter_info(self, fighter_name: str, context_terms: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch fighter information."""
        try:
            logger.info(f"Fetching {self._discipline} info for {fighter_name}")
            return self.build_validated_payload(
                fighter_name,
                self._discipline,
                self._stat_type,
                "fighter",
                context_terms=context_terms,
            )
        except Exception as e:
            logger.error(f"Error fetching {self._discipline} info for {fighter_name}: {e}")
            return None


class BasketballFetcher(DataFetcher):
    """Fetch basketball data from Basketball-Reference and Euroleague official sources."""

    def fetch_team_info(self, team_name: str, context_terms: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch basketball team information."""
        try:
            logger.info(f"Fetching basketball info for {team_name}")
            return self.build_validated_payload(
                team_name,
                "basketball",
                "injuries lineup pace rating recent games",
                "team",
                context_terms=context_terms,
            )
        except Exception as e:
            logger.error(f"Error fetching basketball info for {team_name}: {e}")
            return None


class HockeyFetcher(DataFetcher):
    """Fetch hockey data from EliteProspects, NaturalStatTrick."""

    def fetch_team_info(self, team_name: str, context_terms: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch hockey team information."""
        try:
            logger.info(f"Fetching hockey info for {team_name}")
            return self.build_validated_payload(
                team_name,
                "hockey",
                "injuries roster corsi recent games",
                "team",
                context_terms=context_terms,
            )
        except Exception as e:
            logger.error(f"Error fetching hockey info for {team_name}: {e}")
            return None


class TableTennisFetcher(DataFetcher):
    """Fetch table tennis data from ITTF and Table Tennis Guide."""

    def fetch_player_info(self, player_name: str, context_terms: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch table tennis player information."""
        try:
            logger.info(f"Fetching table tennis info for {player_name}")
            return self.build_validated_payload(
                player_name,
                "table_tennis",
                "ranking results recent matches",
                "player",
                context_terms=context_terms,
            )
        except Exception as e:
            logger.error(f"Error fetching table tennis info for {player_name}: {e}")
            return None


class VolleyballFetcher(DataFetcher):
    """Fetch volleyball data from Volleybox."""

    def fetch_team_info(self, team_name: str, context_terms: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch volleyball team information."""
        try:
            logger.info(f"Fetching volleyball info for {team_name}")
            return self.build_validated_payload(
                team_name,
                "volleyball",
                "roster injuries recent matches",
                "team",
                context_terms=context_terms,
            )
        except Exception as e:
            logger.error(f"Error fetching volleyball info for {team_name}: {e}")
            return None


def _build_context(match_context: dict | None, opponent: str) -> str:
    """Build context terms string from match context and opponent name."""
    if not match_context:
        return opponent
    parts = [opponent, match_context.get("date", ""), match_context.get("league", "")]
    return " ".join(part for part in parts if part)


def fetch_match_analysis_data(
    match_name: str,
    fetcher: DataFetcher,
    fetch_method: str,
    emoji: str,
    match_context: dict | None = None,
) -> str:
    """Unified match data fetcher: parse participants, collect validated sources, return report.

    Used by all sport services. Returns the raw validated report for LLM consumption.
    """
    teams = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s*-\s*", match_name, flags=re.I)
    if len(teams) != 2:
        return f"Матч: {match_name}\n\nНе удалось определить участников матча."

    side1, side2 = teams[0].strip(), teams[1].strip()
    ctx1 = _build_context(match_context, side2)
    ctx2 = _build_context(match_context, side1)

    fetch_fn = getattr(fetcher, fetch_method)
    try:
        data1 = fetch_fn(side1, context_terms=ctx1)
    except Exception as e:
        logger.error("Fetch failed for %s: %s", side1, e)
        data1 = None
    try:
        data2 = fetch_fn(side2, context_terms=ctx2)
    except Exception as e:
        logger.error("Fetch failed for %s: %s", side2, e)
        data2 = None

    parts = [f"{emoji} Матч: {side1.upper()} vs {side2.upper()}"]

    if data1 and data1.get("report"):
        parts.append(f"\n--- {side1.upper()} ---\n{data1['report']}")
    if data2 and data2.get("report"):
        parts.append(f"\n--- {side2.upper()} ---\n{data2['report']}")

    if len(parts) == 1:
        parts.append("\nДанные из поисковых источников не найдены. Анализируйте на основе общих знаний.")

    return "\n".join(parts)

def get_fetcher(discipline: str) -> Optional[DataFetcher]:
    """Get appropriate fetcher for discipline."""
    d = discipline.lower()
    
    if "cs" in d or "counter-strike" in d or "cs2" in d:
        return CS2Fetcher()
    elif "футбол" in d or "football" in d or "soccer" in d:
        return FootballFetcher()
    elif "table" in d or "настольный" in d or "table_tennis" in d:
        return TableTennisFetcher()
    elif "теннис" in d or "tennis" in d:
        return TennisFetcher()
    elif "мма" in d or "бокс" in d or "boxing" in d or "fighting" in d:
        return MMAFetcher()
    elif "баскетбол" in d or "basketball" in d:
        return BasketballFetcher()
    elif "хоккей" in d or "hockey" in d:
        return HockeyFetcher()
    elif "волейбол" in d or "volleyball" in d:
        return VolleyballFetcher()
    
    return None
