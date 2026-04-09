import logging
from datetime import datetime, timedelta
from typing import List, Optional
from urllib.parse import quote_plus

import httpx

THESPORTSDB_EVENT_URL = "https://www.thesportsdb.com/api/v1/json/1/searchevents.php?e={query}"
THESPORTSDB_EVENTS_BY_TEAM_URL = "https://www.thesportsdb.com/api/v1/json/1/eventsnext.php?id={team_id}"
THESPORTSDB_SEARCH_TEAM_URL = "https://www.thesportsdb.com/api/v1/json/1/searchteams.php?t={query}"


def search_event_thesportsdb(match_name: str) -> dict | None:
    try:
        query = quote_plus(match_name)
        url = THESPORTSDB_EVENT_URL.format(query=query)
        response = httpx.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        events = data.get("event")
        if not events:
            logging.debug("No events found in TheSportsDB for '%s'", match_name)
            return None
        return events[0]
    except httpx.ConnectError as e:
        logging.warning("TheSportsDB connection error for '%s': %s", match_name, e)
        return None
    except httpx.TimeoutException as e:
        logging.warning("TheSportsDB timeout for '%s': %s", match_name, e)
        return None
    except httpx.HTTPStatusError as e:
        logging.warning("TheSportsDB HTTP error for '%s': %s", match_name, e)
        return None
    except (ValueError, KeyError) as e:
        logging.warning("TheSportsDB parse error for '%s': %s", match_name, e)
        return None


def _search_team_id(team_name: str) -> Optional[str]:
    """Ищет ID команды в TheSportsDB по названию."""
    try:
        url = THESPORTSDB_SEARCH_TEAM_URL.format(query=quote_plus(team_name))
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        teams = resp.json().get("teams")
        if teams:
            return teams[0].get("idTeam")
    except Exception as e:
        logging.debug("TheSportsDB team search error for '%s': %s", team_name, e)
    return None


def search_upcoming_events_by_team(
    team_name: str,
    opponent_name: Optional[str] = None,
    target_date: Optional[datetime] = None,
    days_range: int = 3,
) -> List[dict]:
    """Ищет ближайшие матчи команды, опционально фильтруя по сопернику и дате."""
    team_id = _search_team_id(team_name)
    if not team_id:
        return []
    try:
        url = THESPORTSDB_EVENTS_BY_TEAM_URL.format(team_id=team_id)
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        events = resp.json().get("events") or []
    except Exception as e:
        logging.debug("TheSportsDB upcoming events error: %s", e)
        return []

    results = []
    for ev in events:
        home = ev.get("strHomeTeam", "")
        away = ev.get("strAwayTeam", "")
        date_str = ev.get("dateEvent", "")

        # Фильтр по сопернику
        if opponent_name:
            opp_lower = opponent_name.strip().lower()
            if opp_lower not in home.lower() and opp_lower not in away.lower():
                continue

        # Фильтр по дате (±days_range)
        if target_date and date_str:
            try:
                ev_date = datetime.strptime(date_str, "%Y-%m-%d")
                if abs((ev_date - target_date).days) > days_range:
                    continue
            except ValueError:
                pass

        results.append({
            "home": home,
            "away": away,
            "date": date_str,
            "sport": ev.get("strSport", ""),
            "league": ev.get("strLeague", ""),
        })
    return results
