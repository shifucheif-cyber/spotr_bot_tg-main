"""
Universal data fetching module for match analysis.
Handles verification from multiple sources and data extraction.
"""

import logging
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

    HLTV_BASE = "https://www.hltv.org"
    LIQUIPEDIA_BASE = "https://liquipedia.net/counterstrike"

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

    def _fetch_hltv_match(self, team1: str, team2: str) -> Optional[Dict[str, Any]]:
        """Fetch from HLTV."""
        try:
            stats_data = search_cs2_stats(team1)
            logger.info(f"HLTV search completed for {team1}")
            return {
                "source": "HLTV",
                "team": team1,
                "data": stats_data,
                "status": "completed"
            }
        except Exception as e:
            logger.warning(f"HLTV fetch failed: {e}")
            return None

    def _fetch_liquipedia_match(self, team1: str, team2: str) -> Optional[Dict[str, Any]]:
        """Fetch from Liquipedia."""
        try:
            # Liquipedia included in search_cs2_stats via site:liquipedia.net
            stats_data = search_cs2_stats(f"{team1} vs {team2}")
            logger.info(f"Liquipedia search completed for {team1} vs {team2}")
            return {
                "source": "Liquipedia",
                "match": f"{team1} vs {team2}",
                "data": stats_data,
                "status": "completed"
            }
        except Exception as e:
            logger.warning(f"Liquipedia fetch failed: {e}")
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

    WHOSCORED_BASE = "https://www.whoscored.com"
    FLASHSCORE_BASE = "https://www.flashscore.com"
    TRANSFERMARKT_BASE = "https://www.transfermarkt.com"

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

    def _fetch_whoscored(self, team_name: str) -> Dict[str, Any]:
        """Fetch from WhoScored."""
        try:
            data = search_football_stats(team_name)
            return {"source": "WhoScored", "data": data, "status": "completed"}
        except Exception as e:
            logger.warning(f"WhoScored fetch failed: {e}")
            return {"source": "WhoScored", "status": "failed"}

    def _fetch_flashscore(self, team_name: str) -> Dict[str, Any]:
        """Fetch from Flashscore."""
        try:
            data = search_football_stats(team_name)
            return {"source": "Flashscore", "data": data, "status": "completed"}
        except Exception as e:
            logger.warning(f"Flashscore fetch failed: {e}")
            return {"source": "Flashscore", "status": "failed"}

    def _fetch_transfermarkt(self, team_name: str) -> Dict[str, Any]:
        """Fetch from Transfermarkt."""
        try:
            data = search_football_stats(team_name)
            return {"source": "Transfermarkt", "data": data, "status": "completed"}
        except Exception as e:
            logger.warning(f"Transfermarkt fetch failed: {e}")
            return {"source": "Transfermarkt", "status": "failed"}


class TennisFetcher(DataFetcher):
    """Fetch tennis data from ATP/WTA and Tennis Explorer."""

    ATP_BASE = "https://www.atptour.com"
    WTA_BASE = "https://www.wtatennis.com"
    TENNIS_EXPLORER_BASE = "https://www.tennisexplorer.com"

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

    def _fetch_atp_wta(self, player_name: str) -> Dict[str, Any]:
        """Fetch from ATP/WTA Tour."""
        try:
            data = search_tennis_player(player_name)
            return {"source": "ATP/WTA", "data": data, "status": "completed"}
        except Exception as e:
            logger.warning(f"ATP/WTA fetch failed: {e}")
            return {"source": "ATP/WTA", "status": "failed"}

    def _fetch_tennis_explorer(self, player_name: str) -> Dict[str, Any]:
        """Fetch from Tennis Explorer."""
        try:
            data = search_tennis_player(player_name)
            return {"source": "TennisExplorer", "data": data, "status": "completed"}
        except Exception as e:
            logger.warning(f"Tennis Explorer fetch failed: {e}")
            return {"source": "TennisExplorer", "status": "failed"}


class MMAFetcher(DataFetcher):
    """Fetch MMA/Boxing data from Sherdog, UFC Stats, and BoxRec."""

    SHERDOG_BASE = "https://www.sherdog.com"
    TAPOLOGY_BASE = "https://www.ufcstats.com"
    BOXREC_BASE = "https://www.boxrec.com"

    def fetch_fighter_info(self, fighter_name: str, context_terms: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch fighter information."""
        try:
            logger.info(f"Fetching MMA/Boxing info for {fighter_name}")
            return self.build_validated_payload(
                fighter_name,
                "mma",
                "record reach striking takedowns recent fight",
                "fighter",
                context_terms=context_terms,
            )
        except Exception as e:
            logger.error(f"Error fetching MMA info for {fighter_name}: {e}")
            return None

    def _fetch_sherdog(self, fighter_name: str) -> Dict[str, Any]:
        """Fetch from Sherdog."""
        try:
            data = search_mma_fighter(fighter_name)
            return {"source": "Sherdog", "data": data, "status": "completed"}
        except Exception as e:
            logger.warning(f"Sherdog fetch failed: {e}")
            return {"source": "Sherdog", "status": "failed"}

    def _fetch_tapology(self, fighter_name: str) -> Dict[str, Any]:
        """Fetch from Tapology."""
        try:
            data = search_mma_fighter(fighter_name)
            return {"source": "Tapology", "data": data, "status": "completed"}
        except Exception as e:
            logger.warning(f"Tapology fetch failed: {e}")
            return {"source": "Tapology", "status": "failed"}

    def _fetch_boxrec(self, fighter_name: str) -> Dict[str, Any]:
        """Fetch from BoxRec."""
        try:
            data = search_boxing_fighter(fighter_name)
            return {"source": "BoxRec", "data": data, "status": "completed"}
        except Exception as e:
            logger.warning(f"BoxRec fetch failed: {e}")
            return {"source": "BoxRec", "status": "failed"}


class BasketballFetcher(DataFetcher):
    """Fetch basketball data from Basketball-Reference and Euroleague official sources."""

    NBA_BASE = "https://www.basketball-reference.com"
    EUROLEAGUE_BASE = "https://www.euroleaguebasketball.net"
    REALGM_BASE = "https://www.euroleaguebasketball.net"

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

    def _fetch_nba(self, team_name: str) -> Dict[str, Any]:
        """Fetch from NBA.com."""
        try:
            data = search_basketball_team(team_name)
            return {"source": "NBA", "data": data, "status": "completed"}
        except Exception as e:
            logger.warning(f"NBA fetch failed: {e}")
            return {"source": "NBA", "status": "failed"}

    def _fetch_euroleague(self, team_name: str) -> Dict[str, Any]:
        """Fetch from EuroLeague."""
        try:
            data = search_basketball_team(team_name)
            return {"source": "EuroLeague", "data": data, "status": "completed"}
        except Exception as e:
            logger.warning(f"EuroLeague fetch failed: {e}")
            return {"source": "EuroLeague", "status": "failed"}

    def _fetch_realgm(self, team_name: str) -> Dict[str, Any]:
        """Fetch from RealGM."""
        try:
            data = search_basketball_team(team_name)
            return {"source": "RealGM", "data": data, "status": "completed"}
        except Exception as e:
            logger.warning(f"RealGM fetch failed: {e}")
            return {"source": "RealGM", "status": "failed"}


class HockeyFetcher(DataFetcher):
    """Fetch hockey data from EliteProspects, NaturalStatTrick."""

    ELITEPROSPECTS_BASE = "https://www.eliteprospects.com"
    NST_BASE = "https://www.naturalstattrick.com"

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

    def _fetch_eliteprospects(self, team_name: str) -> Dict[str, Any]:
        """Fetch from EliteProspects."""
        try:
            data = search_hockey_team(team_name)
            return {"source": "EliteProspects", "data": data, "status": "completed"}
        except Exception as e:
            logger.warning(f"EliteProspects fetch failed: {e}")
            return {"source": "EliteProspects", "status": "failed"}

    def _fetch_nst(self, team_name: str) -> Dict[str, Any]:
        """Fetch from NaturalStatTrick."""
        try:
            data = search_hockey_team(team_name)
            return {"source": "NST", "data": data, "status": "completed"}
        except Exception as e:
            logger.warning(f"NST fetch failed: {e}")
            return {"source": "NST", "status": "failed"}


class TableTennisFetcher(DataFetcher):
    """Fetch table tennis data from ITTF and Table Tennis Guide."""

    ITTF_BASE = "https://www.ittfworld.com"
    FLASHSCORE_BASE = "https://www.tabletennis-guide.com"
    STATSBOMB_BASE = "https://www.tabletennis-guide.com"

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

    def _fetch_ittf(self, player_name: str) -> Dict[str, Any]:
        """Fetch from ITTF World Rankings."""
        try:
            data = search_table_tennis_player(player_name)
            return {"source": "ITTF", "data": data, "status": "completed"}
        except Exception as e:
            logger.warning(f"ITTF fetch failed: {e}")
            return {"source": "ITTF", "status": "failed"}

    def _fetch_flashscore(self, player_name: str) -> Dict[str, Any]:
        """Fetch from Flashscore Table Tennis."""
        try:
            data = search_table_tennis_player(player_name)
            return {"source": "Flashscore", "data": data, "status": "completed"}
        except Exception as e:
            logger.warning(f"Flashscore fetch failed: {e}")
            return {"source": "Flashscore", "status": "failed"}

    def _fetch_statsbomb(self, player_name: str) -> Dict[str, Any]:
        """Fetch from StatsTable/StatsStats."""
        try:
            data = search_table_tennis_player(player_name)
            return {"source": "StatsTable", "data": data, "status": "completed"}
        except Exception as e:
            logger.warning(f"StatsTable fetch failed: {e}")
            return {"source": "StatsTable", "status": "failed"}


class VolleyballFetcher(DataFetcher):
    """Fetch volleyball data from Volleybox."""

    WORLDOFVOLLEY_BASE = "https://www.volleybox.net"
    VOLLEYBOX_BASE = "https://www.volleybox.net"

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

    def _fetch_worldofvolley(self, team_name: str) -> Dict[str, Any]:
        """Fetch from WorldofVolley."""
        try:
            data = search_volleyball_team(team_name)
            return {"source": "WorldofVolley", "data": data, "status": "completed"}
        except Exception as e:
            logger.warning(f"WorldofVolley fetch failed: {e}")
            return {"source": "WorldofVolley", "status": "failed"}

    def _fetch_volleybox(self, team_name: str) -> Dict[str, Any]:
        """Fetch from Volleybox."""
        try:
            data = search_volleyball_team(team_name)
            return {"source": "Volleybox", "data": data, "status": "completed"}
        except Exception as e:
            logger.warning(f"Volleybox fetch failed: {e}")
            return {"source": "Volleybox", "status": "failed"}


# Factory for creating appropriate fetcher
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
