"""
Universal data fetching module for match analysis.
Handles verification from multiple sources and data extraction.
"""

import hashlib
import logging
import re
import requests
import threading
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone

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

# ── Match analysis cache ──
# Key: hash(discipline, sorted participants) → {"result": str, "ts": datetime}
_match_cache: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL = timedelta(days=2)  # кэш: события старше 2 дней удаляются
_CACHE_MAX = 200
_cache_lock = threading.Lock()


def _cache_key(discipline: str, side1: str, side2: str, match_date: str = "") -> str:
    """Детерминированный ключ: дисциплина + отсортированные участники + дата."""
    parts = sorted([side1.strip().lower(), side2.strip().lower()])
    raw = f"{discipline.strip().lower()}|{parts[0]}|{parts[1]}|{match_date.strip().lower()}"
    return hashlib.md5(raw.encode()).hexdigest()


def _get_cached(key: str) -> Optional[str]:
    with _cache_lock:
        entry = _match_cache.get(key)
        if not entry:
            return None
        if datetime.now(tz=timezone.utc) - entry["ts"] > _CACHE_TTL:
            del _match_cache[key]
            return None
        logger.info("Cache hit for match analysis (key=%s)", key[:8])
        return entry["result"]


def _put_cache(key: str, result: str) -> None:
    with _cache_lock:
        if len(_match_cache) >= _CACHE_MAX:
            # удаляем самый старый
            oldest = min(_match_cache, key=lambda k: _match_cache[k]["ts"])
            del _match_cache[oldest]
        _match_cache[key] = {"result": result, "ts": datetime.now(tz=timezone.utc)}

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
                "HLTV rating roster map pool ban pick player form recent results roster changes",
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
                "h2h map veto roster form HLTV rating recent results",
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
            "team_stat_type": "hero pool draft meta patch winrate early game aggression roster form recent results",
            "match_stat_type": "h2h stand-ins draft meta hero bans brackets recent results",
            "team_search": search_dota_stats,
        },
        "lol": {
            "team_stat_type": "champion priority draft meta dragon baron control early game gold lead roster form recent results",
            "match_stat_type": "h2h draft champion bans roster changes objective control recent results",
            "team_search": search_lol_stats,
        },
        "valorant": {
            "team_stat_type": "agent picks map win rates clutch stats eco rounds ACS rating roster form recent results",
            "match_stat_type": "h2h map veto agent picks roster changes clutch stats recent results",
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
                "injuries suspensions lineup xG cards home away form recent results standings motivation",
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
                "ranking h2h surface win rate serve percentage break points injuries fatigue recent matches form",
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
            "record titles ranking opposition reach punch output KO ratio power footwork recent fight camp"
            if self._discipline == "boxing"
            else "record reach striking accuracy takedown defense cardio ground game submissions recent fight camp"
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
                "injuries lineup pace offensive defensive rating rebounds turnovers bench scoring home away form recent results standings",
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
                "injuries roster power play penalty kill goalie save percentage home away form recent results standings h2h",
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
                "ranking h2h style matchup recent series results form world tour standings",
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
                "roster injuries serve reception attack efficiency setter form home away recent results standings h2h",
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

    logger.info(f"[FETCH] Начало анализа: match_name={match_name}, fetcher={fetcher}, fetch_method={fetch_method}, emoji={emoji}, match_context={match_context}")
    teams = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s*-\s*", match_name, flags=re.I)
    if len(teams) != 2:
        logger.warning(f"[FETCH] Не удалось определить участников матча: {match_name}")
        return f"Матч: {match_name}\n\nНе удалось определить участников матча."

    side1, side2 = teams[0].strip(), teams[1].strip()
    logger.info(f"[FETCH] Участники: side1={side1}, side2={side2}")

    # ── Проверяем кэш (одинаковые участники + дисциплина + дата) ──
    discipline = getattr(fetcher, '_discipline', None) or getattr(fetcher, 'game_key', None) or fetcher.__class__.__name__.replace('Fetcher', '').lower()
    match_date = (match_context or {}).get("date", "")
    cache_k = _cache_key(discipline, side1, side2, match_date)
    cached = _get_cached(cache_k)
    if cached is not None:
        logger.info(f"[FETCH] Найден кэш для ключа: {cache_k}")
        return cached

    ctx1 = _build_context(match_context, side2)
    ctx2 = _build_context(match_context, side1)
    logger.info(f"[FETCH] Контекст для side1: {ctx1}")
    logger.info(f"[FETCH] Контекст для side2: {ctx2}")

    fetch_fn = getattr(fetcher, fetch_method)
    try:
        logger.info(f"[FETCH] Запрос данных для side1: {side1}")
        data1 = fetch_fn(side1, context_terms=ctx1)
        logger.info(f"[FETCH] Данные side1 получены: {bool(data1)}")
    except Exception as e:
        logger.error("[FETCH] Fetch failed for %s: %s", side1, e)
        data1 = None
    try:
        logger.info(f"[FETCH] Запрос данных для side2: {side2}")
        data2 = fetch_fn(side2, context_terms=ctx2)
        logger.info(f"[FETCH] Данные side2 получены: {bool(data2)}")
    except Exception as e:
        logger.error("[FETCH] Fetch failed for %s: %s", side2, e)
        data2 = None

    # --- Новый блок: сбор тотала и H2H через профильные библиотеки ---
    total_line = ""
    h2h_line = ""
    try:
        if discipline in ("football", "футбол"):
            from sportsipy.football.teams import Teams
            teams = list(Teams())
            t1 = next((t for t in teams if side1.lower() in t.name.lower()), None)
            t2 = next((t for t in teams if side2.lower() in t.name.lower()), None)
            if t1 and t2:
                t1_goals = [g for g in t1.schedule.dataframe['points_for'][-5:]]
                t2_goals = [g for g in t2.schedule.dataframe['points_for'][-5:]]
                avg_total = (sum(t1_goals) + sum(t2_goals)) / (len(t1_goals) + len(t2_goals))
                total_line = f"🎯 Тотал (средний за 5 игр): {avg_total:.2f}"
                h2h = t1.schedule.dataframe[t1.schedule.dataframe['opponent_name'] == t2.name]
                if not h2h.empty:
                    h2h_line = f"🤝 H2H: {t1.name} vs {t2.name} — {len(h2h)} игр, {h2h['points_for'].sum()}:{h2h['points_against'].sum()} по голам"
        elif discipline in ("hockey", "хоккей"):
            from sportsipy.nhl.teams import Teams as NHLTeams
            teams = list(NHLTeams())
            t1 = next((t for t in teams if side1.lower() in t.name.lower()), None)
            t2 = next((t for t in teams if side2.lower() in t.name.lower()), None)
            if t1 and t2:
                t1_goals = [g for g in t1.schedule.dataframe['goals_for'][-5:]]
                t2_goals = [g for g in t2.schedule.dataframe['goals_for'][-5:]]
                avg_total = (sum(t1_goals) + sum(t2_goals)) / (len(t1_goals) + len(t2_goals))
                total_line = f"🎯 Тотал (средний за 5 игр): {avg_total:.2f}"
                h2h = t1.schedule.dataframe[t1.schedule.dataframe['opponent_name'] == t2.name]
                if not h2h.empty:
                    h2h_line = f"🤝 H2H: {t1.name} vs {t2.name} — {len(h2h)} игр, {h2h['goals_for'].sum()}:{h2h['goals_against'].sum()} по шайбам"
        elif discipline in ("cs2", "csgo", "counter-strike 2"):
            try:
                from hltv import HLTV
                hltv = HLTV()
                matches = hltv.get_matches()
                found = [m for m in matches if side1.lower() in m['team1']['name'].lower() and side2.lower() in m['team2']['name'].lower()]
                if found:
                    match_id = found[0]['id']
                    stats = hltv.get_match_stats(match_id)
                    if stats and 'maps' in stats:
                        total_maps = sum(m['team1Rounds'] + m['team2Rounds'] for m in stats['maps']) / len(stats['maps'])
                        total_line = f"🎯 Тотал карт: {total_maps:.2f}"
            except Exception as e:
                logger.warning(f"HLTV fetch failed: {e}")
        elif discipline in ("basketball", "баскетбол"):
            try:
                from sportsipy.nba.teams import Teams as NBATeams
                teams = list(NBATeams())
                t1 = next((t for t in teams if side1.lower() in t.name.lower()), None)
                t2 = next((t for t in teams if side2.lower() in t.name.lower()), None)
                if t1 and t2:
                    t1_pts = [g for g in t1.schedule.dataframe['points_for'][-5:]]
                    t2_pts = [g for g in t2.schedule.dataframe['points_for'][-5:]]
                    avg_total = (sum(t1_pts) + sum(t2_pts)) / (len(t1_pts) + len(t2_pts))
                    total_line = f"🎯 Тотал (средний за 5 игр): {avg_total:.2f}"
                    h2h = t1.schedule.dataframe[t1.schedule.dataframe['opponent_name'] == t2.name]
                    if not h2h.empty:
                        h2h_line = f"🤝 H2H: {t1.name} vs {t2.name} — {len(h2h)} игр, {h2h['points_for'].sum()}:{h2h['points_against'].sum()} по очкам"
            except Exception as e:
                logger.warning(f"NBA fetch failed: {e}")
        elif discipline in ("volleyball", "волейбол"):
            # Нет официальной библиотеки, только заглушка
            total_line = "🎯 Тотал: статистика тотала по сетам/очкам недоступна (нет открытого API)"
        elif discipline in ("tennis", "теннис"):
            # Тотал по сетам — среднее за 5 последних матчей, если есть данные
            total_line = "🎯 Тотал: среднее количество сетов за 5 последних матчей (нет открытого API)"
        elif discipline in ("table_tennis", "настольный теннис"):
            total_line = "🎯 Тотал: среднее количество сетов за 5 последних матчей (нет открытого API)"
    except Exception as e:
        logger.warning(f"Extra stats fetch failed: {e}")

    parts = [f"{emoji} Матч: {side1.upper()} vs {side2.upper()}"]
    if total_line:
        parts.append(total_line)
    if h2h_line:
        parts.append(h2h_line)

    if data1 and data1.get("report"):
        parts.append(f"\n--- {side1.upper()} ---\n{data1['report']}")
    if data2 and data2.get("report"):
        parts.append(f"\n--- {side2.upper()} ---\n{data2['report']}")

    if len(parts) == 1:
        parts.append("\nДанные из поисковых источников не найдены. Анализируйте на основе общих знаний.")

    result = "\n".join(parts)
    _put_cache(cache_k, result)
    return result


def cleanup_expired_cache() -> int:
    """Удаляет устаревшие записи кэша. Возвращает количество удалённых."""
    with _cache_lock:
        now = datetime.now(tz=timezone.utc)
        expired = [k for k, v in _match_cache.items() if now - v["ts"] > _CACHE_TTL]
        for k in expired:
            del _match_cache[k]
        if expired:
            logger.info("Cache cleanup: removed %d expired entries, %d remaining", len(expired), len(_match_cache))
        return len(expired)
