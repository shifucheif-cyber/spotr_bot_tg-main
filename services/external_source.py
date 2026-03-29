import logging
from urllib.parse import quote_plus

import requests

THESPORTSDB_EVENT_URL = "https://www.thesportsdb.com/api/v1/json/1/searchevents.php?e={query}"


def search_event_thesportsdb(match_name: str) -> dict | None:
    try:
        query = quote_plus(match_name)
        url = THESPORTSDB_EVENT_URL.format(query=query)
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        events = data.get("event")
        if not events:
            return None
        return events[0]
    except Exception as e:
        logging.warning("External source search failed for '%s': %s", match_name, e)
        return None
