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
            logging.debug("No events found in TheSportsDB for '%s'", match_name)
            return None
        return events[0]
    except requests.ConnectionError as e:
        logging.warning("TheSportsDB connection error for '%s': %s", match_name, e)
        return None
    except requests.Timeout as e:
        logging.warning("TheSportsDB timeout for '%s': %s", match_name, e)
        return None
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            logging.debug("TheSportsDB API endpoint unavailable (404) for '%s'", match_name)
        else:
            logging.warning("TheSportsDB HTTP error for '%s': %s", match_name, e)
        return None
    except (ValueError, KeyError) as e:
        logging.warning("TheSportsDB parse error for '%s': %s", match_name, e)
        return None
