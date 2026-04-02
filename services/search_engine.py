"""Search and validation helpers for multi-source sports data collection."""

import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import cloudscraper
import requests
from bs4 import BeautifulSoup
from services.name_normalizer import expand_context_terms, get_search_variants, normalize_entity_name, split_match_text, transliterate_text
try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None
try:
    from exa_py import Exa as ExaClient
except ImportError:
    ExaClient = None
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS
try:
    from googlesearch import search as google_search_lib
except ImportError:
    google_search_lib = None

logger = logging.getLogger(__name__)

# ── Shared cloudscraper session (bypasses JS challenges / Cloudflare) ──
_scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows"},
    delay=3,
)

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
REQUEST_TIMEOUT = 10
GOOGLE_SEARCH_URL = "https://www.google.com/search"
ENABLE_GOOGLE_SEARCH = os.getenv("ENABLE_GOOGLE_SEARCH", "false").strip().lower() in {"1", "true", "yes", "on"}
SEARCH_MAX_SITES = max(1, int(os.getenv("SEARCH_MAX_SITES", "4")))
SEARCH_RESULTS_PER_QUERY = max(1, int(os.getenv("SEARCH_RESULTS_PER_QUERY", "1")))
SEARCH_ENABLE_BROAD_WINDOW = os.getenv("SEARCH_ENABLE_BROAD_WINDOW", "false").strip().lower() in {"1", "true", "yes", "on"}
SEARCH_REGION = os.getenv("SEARCH_REGION", "wt-wt")
EXA_API_KEY = os.getenv("EXA_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
SEARCH_ANALYSIS_PROVIDER = os.getenv("SEARCH_ANALYSIS_PROVIDER", "hybrid").strip().lower()
SEARCH_ANALYSIS_RESULTS_PER_QUERY = max(1, int(os.getenv("SEARCH_ANALYSIS_RESULTS_PER_QUERY", "2")))
SEARCH_ANALYSIS_MAX_SNIPPETS = max(1, int(os.getenv("SEARCH_ANALYSIS_MAX_SNIPPETS", "4")))
GOOGLE_BACKOFF_SECONDS = max(60, int(os.getenv("GOOGLE_BACKOFF_SECONDS", "900")))
_google_backoff_until = 0.0
RUSSIAN_CONTEXT_HINTS = {
    "рпл", "фнл", "кубок россии", "кхл", "вхл", "мхл", "единая лига втб",
    "суперлига", "вфв", "aca", "rcc", "fight nights", "рtt", "ртт", "снг",
    "восточная европа", "россия", "russia", "russian",
}
RUSSIAN_PARTICIPANT_HINTS = {
    "football": {
        "зенит", "спартак", "цска", "локомотив", "динамо москва", "краснодар", "ростов",
        "рубин", "ахмат", "крылья советов", "оренбург", "факел", "пари нн", "урал", "сочи",
        "zenit", "spartak", "cska", "lokomotiv", "lokomotiv moscow", "dynamo moscow",
        "dinamo moscow", "krasnodar", "rostov", "rubin", "akhmat", "krylia sovetov",
        "orenburg", "fakel", "pari nn", "ural", "sochi",
    },
    "hockey": {
        "ска", "цска", "спартак", "динамо москва", "авангард", "ак барс", "салават юлаев",
        "локомотив", "металлург магнитогорск", "трактор", "северсталь", "торпедо нн", "автомобилист",
        "ska", "cska", "spartak", "dynamo moscow", "dinamo moscow", "avangard", "ak bars",
        "salavat yulaev", "lokomotiv yaroslavl", "metallurg magnitogorsk", "traktor", "severstal",
        "torpedo nizhny novgorod", "avtomobilist",
    },
    "basketball": {
        "зенит", "цска", "уникс", "локомотив кубань", "парма пермь", "самара", "автодор",
        "нижний новгород", "мба", "уралмаш",
        "zenit", "cska", "unics", "lokomotiv kuban", "parma perm", "samara", "avtodor",
        "nizhny novgorod", "mba moscow", "uralmash",
    },
    "volleyball": {
        "зенит казань", "зенит спб", "динамо москва", "локомотив новосибирск", "белогорье",
        "зенит", "динамо", "lokomotiv novosibirsk", "belogorie", "zenit kazan", "zenit st petersburg",
        "dynamo moscow", "zenit", "dynamo",
    },
    "tennis": {
        "медведев", "рублев", "хачанов", "касаткина", "кудерметова", "андреева", "калинская",
        "павлюченкова", "alexandrova", "medvedev", "rublev", "khachanov", "kasatkina",
        "kudermetova", "andreeva", "kalinskaya", "pavlyuchenkova",
    },
    "table_tennis": {
        "шибаев", "карташев", "сидоренко", "полина михайлова", "лилия гуракова",
        "shibaev", "kartashev", "sidorenko", "polina mikhailova", "liliya gurakova",
    },
    "mma": {
        "ислам махачев", "петр ян", "магомед анкалаев", "александр волков", "федор емельяненко",
        "шара буллет", "makhachev", "petr yan", "ankalaev", "volkov", "emelianenko", "shara bullet",
    },
    "boxing": {
        "бивол", "бетербиев", "батыргазиев", "кузямин", "dmitry bivol", "artur beterbiev",
        "batyrgaziev", "kovalev",
    },
    "cs2": {
        "team spirit", "virtus pro", "virtus.pro", "betboom", "forze", "1win", "parivision",
        "дух", "виртус про", "бетбум",
    },
    "dota2": {
        "team spirit", "betboom", "parivision", "virtus pro", "virtus.pro", "9pandas",
        "дух", "бетбум", "виртус про",
    },
    "valorant": {
        "team spirit", "forze", "1win", "дух", "форз", "1вин",
    },
    "lol": {
        "unicorns of love", "virtus pro", "virtus.pro", "vega squadron", "единороги любви", "виртус про",
    },
}

DISCIPLINE_SOURCE_CONFIG = {
    "football": [
        {"site": "premierliga.ru", "label": "RPL Official", "focus": "official lineups protocols player stats", "region": "ru"},
        {"site": "soccer.ru", "label": "Soccer.ru", "focus": "injuries suspensions russian football news", "region": "ru"},
        {"site": "sports.ru", "label": "Sports.ru", "focus": "blogs tactical analysis rpl fnl russian cup", "region": "ru"},
        {"site": "rustat.pro", "label": "Rustat", "focus": "russian football advanced analytics player and team metrics", "region": "ru"},
        {"site": "whoscored.com", "label": "WhoScored", "focus": "player ratings weak defense style of play"},
        {"site": "transfermarkt.com", "label": "Transfermarkt", "focus": "injuries suspensions market value transfers"},
        {"site": "flashscore.com", "label": "Flashscore", "focus": "lineups live stats"},
        {"site": "sofascore.com", "label": "SofaScore", "focus": "live score h2h lineups player ratings"},
        {"site": "fotmob.com", "label": "FotMob", "focus": "live score predicted lineups h2h stats"},
        {"site": "fbref.com", "label": "FBref", "focus": "xg sca pressing advanced stats"},
    ],
    "tennis": [
        {"site": "rtt-tennis.ru", "label": "RTT Tennis", "focus": "russian tennis tour draws rankings juniors adults", "region": "ru"},
        {"site": "tennisexplorer.com", "label": "Tennis Explorer", "focus": "h2h surface results"},
        {"site": "ultimatetennisstatistics.com", "label": "Ultimate Tennis Statistics", "focus": "fatigue first serve second serve physical indicators"},
    ],
    "table_tennis": [
        {"site": "ittf.com", "label": "ITTF", "focus": "official ranking major tournament results"},
        {"site": "tabletennis-guide.com", "label": "Table Tennis Guide", "focus": "equipment pips inverted style matchup"},
    ],
    "mma": [
        {"site": "aca-mma.com", "label": "ACA MMA", "focus": "russian league results fighter stats cards", "region": "ru"},
        {"site": "fighttime.ru", "label": "FightTime", "focus": "cis fighter rankings calendars russian mma news", "region": "ru"},
        {"site": "sherdog.com", "label": "Sherdog", "focus": "fight history reach gyms"},
        {"site": "ufcstats.com", "label": "UFC Stats", "focus": "striking accuracy takedown defense control time"},
    ],
    "boxing": [
        {"site": "allboxing.ru", "label": "AllBoxing", "focus": "russian professional boxing news results interviews", "region": "ru"},
        {"site": "boxrec.com", "label": "BoxRec", "focus": "verified record titles strength of opposition"},
    ],
    "hockey": [
        {"site": "khl.ru", "label": "KHL Official", "focus": "ice time distance shot speed faceoffs official stats", "region": "ru"},
        {"site": "allhockey.ru", "label": "AllHockey", "focus": "transfers insider news player condition locker room", "region": "ru"},
        {"site": "r-hockey.ru", "label": "R-Hockey", "focus": "player database youth leagues career history", "region": "ru"},
        {"site": "eliteprospects.com", "label": "Elite Prospects", "focus": "rosters transfers goals assists"},
        {"site": "naturalstattrick.com", "label": "Natural Stat Trick", "focus": "corsi fenwick xgf xga"},
        {"site": "liveresult.ru", "label": "LiveResult", "focus": "khl europe quick results"},
    ],
    "basketball": [
        {"site": "vtb-league.com", "label": "VTB United League", "focus": "official vtb league efficiency ratings rosters match protocols", "region": "ru"},
        {"site": "basketball-reference.com", "label": "Basketball-Reference", "focus": "pace offensive efficiency complete nba database"},
        {"site": "euroleaguebasketball.net", "label": "Euroleague Official", "focus": "official euroleague and eurocup stats"},
    ],
    "volleyball": [
        {"site": "volley.ru", "label": "Volley.ru", "focus": "official russian volleyball match protocols attacks blocks", "region": "ru"},
        {"site": "sport.business-gazeta.ru", "label": "BO Sport", "focus": "russian volleyball analysis insider coverage", "region": "ru"},
        {"site": "volleybox.net", "label": "Volleybox", "focus": "rosters transfers leader status"},
    ],
    "cs2": [
        {"site": "cyber.sports.ru", "label": "Cyber Sports.ru", "focus": "cis roster changes interviews regional news", "region": "ru"},
        {"site": "cybersport.ru", "label": "Cybersport.ru", "focus": "regional qualifiers brackets cis match center", "region": "ru"},
        {"site": "hltv.org", "label": "HLTV", "focus": "map pool pistol rounds rating 2.0"},
        {"site": "liquipedia.net", "label": "Liquipedia", "focus": "brackets stand-ins schedule"},
    ],
    "dota2": [
        {"site": "cyber.sports.ru", "label": "Cyber Sports.ru", "focus": "cis roster changes interviews regional news", "region": "ru"},
        {"site": "cybersport.ru", "label": "Cybersport.ru", "focus": "regional qualifiers brackets cis match center", "region": "ru"},
        {"site": "dotabuff.com", "label": "Dotabuff", "focus": "hero meta pub stats pro player form"},
        {"site": "liquipedia.net", "label": "Liquipedia", "focus": "brackets stand-ins schedule"},
    ],
    "valorant": [
        {"site": "cyber.sports.ru", "label": "Cyber Sports.ru", "focus": "cis roster changes interviews regional news", "region": "ru"},
        {"site": "cybersport.ru", "label": "Cybersport.ru", "focus": "regional qualifiers brackets cis match center", "region": "ru"},
        {"site": "vlr.gg", "label": "VLR", "focus": "map stats agent stats match breakdowns"},
        {"site": "liquipedia.net", "label": "Liquipedia", "focus": "brackets roster changes schedule"},
    ],
    "lol": [
        {"site": "cyber.sports.ru", "label": "Cyber Sports.ru", "focus": "cis roster changes interviews regional news", "region": "ru"},
        {"site": "cybersport.ru", "label": "Cybersport.ru", "focus": "regional qualifiers brackets cis match center", "region": "ru"},
        {"site": "oracleselixir.com", "label": "Oracle's Elixir", "focus": "gold per minute objective control advanced stats"},
        {"site": "liquipedia.net", "label": "Liquipedia", "focus": "brackets roster changes schedule"},
    ],
}

DISCIPLINE_SITES = {
    discipline: [entry["site"] for entry in entries]
    for discipline, entries in DISCIPLINE_SOURCE_CONFIG.items()
}

DISCIPLINE_VALIDATION_ALIASES = {
    "football": "football",
    "soccer": "football",
    "футбол": "football",
    "hockey": "hockey",
    "хоккей": "hockey",
    "basketball": "basketball",
    "баскетбол": "basketball",
    "tennis": "tennis",
    "теннис": "tennis",
    "table tennis": "table_tennis",
    "table_tennis": "table_tennis",
    "настольный теннис": "table_tennis",
    "volleyball": "volleyball",
    "волейбол": "volleyball",
    "mma": "mma",
    "мма": "mma",
    "boxing": "boxing",
    "бокс": "boxing",
    "cs2": "cs2",
    "cs 2": "cs2",
    "counter-strike 2": "cs2",
    "counter strike 2": "cs2",
    "dota2": "dota2",
    "dota 2": "dota2",
    "lol": "lol",
    "league of legends": "lol",
    "valorant": "valorant",
}

CYRILLIC_TO_LATIN = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ы": "y", "э": "e", "ю": "yu", "я": "ya", "ъ": "", "ь": "",
})


def _normalize_tokens(text: str) -> List[str]:
    cleaned = re.sub(r"[^\w\s]", " ", text.lower(), flags=re.UNICODE)
    return [token for token in cleaned.split() if len(token) > 1]


def _extract_source(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return "unknown"


def _transliterate_text(text: str) -> str:
    lowered = text.lower()
    transliterated = lowered.translate(CYRILLIC_TO_LATIN)
    transliterated = re.sub(r"\s+", " ", transliterated).strip()
    return transliterated


def _clean_context_terms(context_terms: Optional[str]) -> str:
    if not context_terms:
        return ""
    cleaned = re.sub(r"\bUser Query\b", "", context_terms, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bunknown\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _looks_like_russian_context(entity: str, context_terms: Optional[str], discipline: str) -> bool:
    haystack = " ".join(part for part in [entity, context_terms or "", discipline] if part).lower()
    return any(hint in haystack for hint in RUSSIAN_CONTEXT_HINTS)


def _looks_like_russian_participant(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"[а-яё]", text.lower()))


def _matches_russian_hint(text: str, discipline: str) -> bool:
    if not text:
        return False

    normalized = normalize_entity_name(text)
    transliterated = normalize_entity_name(transliterate_text(text))
    haystacks = [normalized, transliterated]
    hints = RUSSIAN_PARTICIPANT_HINTS.get(discipline, set())
    if not hints:
        return False

    for haystack in haystacks:
        if not haystack:
            continue
        for hint in hints:
            normalized_hint = normalize_entity_name(hint)
            if normalized_hint and normalized_hint in haystack:
                return True
    return False


def _should_prefer_russian_sources(entity: str, context_terms: Optional[str], discipline: str) -> bool:
    if _looks_like_russian_context(entity, context_terms, discipline):
        return True

    cleaned_context = _clean_context_terms(context_terms)
    if not cleaned_context:
        return False

    entity_is_russian = _looks_like_russian_participant(entity) or _matches_russian_hint(entity, discipline)
    context_is_russian = _looks_like_russian_participant(cleaned_context) or _matches_russian_hint(cleaned_context, discipline)
    return entity_is_russian and context_is_russian


def _get_sites_for_query(discipline: str, entity: str, context_terms: Optional[str] = None) -> List[str]:
    entries = DISCIPLINE_SOURCE_CONFIG.get(discipline, [])
    if not entries:
        return []

    if _should_prefer_russian_sources(entity, context_terms, discipline):
        ordered_entries = [entry for entry in entries if entry.get("region") == "ru"]
        ordered_entries.extend(entry for entry in entries if entry.get("region") != "ru")
    else:
        ordered_entries = [entry for entry in entries if entry.get("region") != "ru"]
        ordered_entries.extend(entry for entry in entries if entry.get("region") == "ru")

    sites: List[str] = []
    seen = set()
    for entry in ordered_entries:
        site = entry["site"]
        if site in seen:
            continue
        seen.add(site)
        sites.append(site)
        if len(sites) >= SEARCH_MAX_SITES:
            break
    return sites


def _build_site_queries(entity: str, site: str, stat_type: str, context_terms: Optional[str] = None) -> List[str]:
    suffix = _clean_context_terms(context_terms)
    queries: List[str] = []
    discipline = None
    for key, sites in DISCIPLINE_SITES.items():
        if site in sites:
            discipline = key
            break

    entity_variants = get_search_variants(entity, discipline=discipline, limit=4)
    if not entity_variants:
        entity_variants = [entity.strip()]

    context_variants = expand_context_terms(suffix, discipline=discipline) if suffix else []
    if suffix and suffix not in context_variants:
        context_variants.insert(0, suffix)
    if not context_variants:
        context_variants = [""]

    for entity_variant in entity_variants[:3]:
        for context_variant in context_variants[:2]:
            tail = f" {context_variant}" if context_variant else ""
            queries.append(f"{entity_variant} {stat_type}{tail} site:{site}".strip())

    deduplicated: List[str] = []
    seen = set()
    for query in queries:
        normalized = query.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduplicated.append(query)
    return deduplicated


def _normalize_validation_discipline_key(discipline: str) -> str:
    cleaned = re.sub(r"\s+", " ", (discipline or "").strip().lower())
    if ":" in cleaned:
        parts = [part.strip() for part in cleaned.split(":") if part.strip()]
        if parts:
            cleaned = parts[-1]
    if cleaned in DISCIPLINE_SOURCE_CONFIG:
        return cleaned
    return DISCIPLINE_VALIDATION_ALIASES.get(cleaned, cleaned)


def _google_is_available() -> bool:
    return ENABLE_GOOGLE_SEARCH and time.monotonic() >= _google_backoff_until


def _set_google_backoff() -> None:
    global _google_backoff_until
    _google_backoff_until = time.monotonic() + GOOGLE_BACKOFF_SECONDS


def _fetch_page_excerpt(url: str, entity: str) -> str:
    try:
        response = _scraper.get(url, timeout=7)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = " ".join(soup.stripped_strings)
        text = re.sub(r"\s+", " ", text)
        if not text:
            return ""

        entity_tokens = _normalize_tokens(entity)
        if entity_tokens:
            pattern = re.compile("|".join(re.escape(token) for token in entity_tokens), re.IGNORECASE)
            match = pattern.search(text)
            if match:
                start = max(0, match.start() - 220)
                end = min(len(text), match.end() + 420)
                return text[start:end]
        return text[:640]
    except Exception as exc:
        logger.debug("Page fetch failed for %s: %s", url, exc)
        return ""


def _is_result_valid(entity: str, title: str, body: str, excerpt: str, url: str = "") -> bool:
    # Include URL path in haystack — URLs like /las-palmas-vs-granada/ contain entity
    url_text = urlparse(url).path.replace("-", " ").replace("_", " ") if url else ""
    haystack = f"{title} {body} {excerpt} {url_text}".lower()
    entity_tokens = _normalize_tokens(entity)
    if not entity_tokens:
        return False

    matched = sum(1 for token in entity_tokens if token in haystack)
    if len(entity_tokens) == 1:
        return matched >= 1
    return matched >= min(2, len(entity_tokens))


def search_with_ddgs(query: str, num_results: int = 5, timelimit: str = "m") -> List[Dict[str, Any]]:
    """Search via DuckDuckGo using ddgs library (v9+)."""
    try:
        ddgs = DDGS()
        kwargs: Dict[str, Any] = {"max_results": num_results}
        if timelimit:
            kwargs["timelimit"] = timelimit
        results = ddgs.text(query, **kwargs)
        if results:
            logger.info("DDG: %d results for: %s", len(results), query)
            return results
        logger.info("DDG: 0 results for: %s", query)
    except Exception as exc:
        logger.debug("DDG failed for '%s': %s", query, exc)
    return []


def search_with_google(query: str, num_results: int = 5) -> List[Dict[str, Any]]:
    """Google search: tries googlesearch-python lib first, then cloudscraper scraping."""
    if not _google_is_available():
        logger.debug("Google search skipped for query '%s'", query)
        return []

    # ── Method 1: googlesearch-python library (cleanest approach) ──
    if google_search_lib is not None:
        try:
            urls = list(google_search_lib(query, num_results=num_results, lang="en", sleep_interval=2))
            if urls:
                results: List[Dict[str, Any]] = []
                for url in urls:
                    if "google.com" in url:
                        continue
                    results.append({
                        "title": url.split("/")[-1].replace("-", " ").replace("_", " ")[:120],
                        "body": "",
                        "href": url,
                        "search_engine": "google",
                    })
                if results:
                    logger.info("Google (lib): %d results for: %s", len(results), query)
                    return results
        except Exception as exc:
            logger.debug("Google (lib) failed for '%s': %s", query, exc)

    # ── Method 2: cloudscraper scraping (fallback) ──
    try:
        response = _scraper.get(
            GOOGLE_SEARCH_URL,
            params={"q": query, "hl": "en", "num": num_results},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        results = []

        # Try /url?q= links first
        for link in soup.select("a[href^='/url?q=']"):
            href = link.get("href", "")
            parsed = parse_qs(urlparse(href).query)
            url = parsed.get("q", [""])[0]
            if not url or "google.com" in url:
                continue
            title_node = link.find("h3")
            title = title_node.get_text(" ", strip=True) if title_node else link.get_text(" ", strip=True)
            parent_text = link.parent.get_text(" ", strip=True) if link.parent else ""
            results.append({"title": title, "body": parent_text[:320], "href": url, "search_engine": "google"})
            if len(results) >= num_results:
                break

        # Fallback: div.g containers
        if not results:
            for div in soup.select("div.g"):
                a_tag = div.find("a", href=True)
                if not a_tag:
                    continue
                url = a_tag["href"]
                if not url.startswith("http") or "google.com" in url:
                    continue
                title = a_tag.get_text(" ", strip=True)
                snippet_tag = div.find("span") or div.find("div", class_="VwiC3b")
                body = snippet_tag.get_text(" ", strip=True) if snippet_tag else ""
                results.append({"title": title, "body": body[:320], "href": url, "search_engine": "google"})
                if len(results) >= num_results:
                    break

        logger.info("Google (scrape): %d results for: %s", len(results), query)
        return results
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 429:
            logger.warning("Google search throttled, backing off for %s seconds", GOOGLE_BACKOFF_SECONDS)
            _set_google_backoff()
        logger.debug("Google search failed for '%s': %s", query, exc)
        return []
    except Exception as exc:
        logger.debug("Google search failed for '%s': %s", query, exc)
        return []


def search_with_bing(query: str, num_results: int = 5) -> List[Dict[str, Any]]:
    """Scrape Bing search results via cloudscraper (bypasses JS challenge)."""
    try:
        response = _scraper.get(
            "https://www.bing.com/search",
            params={"q": query, "count": num_results},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        results: List[Dict[str, Any]] = []
        containers = soup.select("li.b_algo") or soup.select("ol#b_results > li")
        for li in containers:
            a_tag = li.find("a", href=True)
            if not a_tag:
                continue
            url = a_tag["href"]
            if "bing.com" in url or "microsoft.com" in url:
                continue
            title = a_tag.get_text(" ", strip=True)
            snippet_tag = li.find("p") or li.find("div", class_="b_caption") or li.find("span")
            body = snippet_tag.get_text(" ", strip=True) if snippet_tag else ""
            results.append({"title": title, "body": body[:320], "href": url, "search_engine": "bing"})
            if len(results) >= num_results:
                break
        logger.info("Bing: %d results for: %s", len(results), query)
        return results
    except Exception as exc:
        logger.debug("Bing search failed for '%s': %s", query, exc)
        return []


def search_with_yahoo(query: str, num_results: int = 5) -> List[Dict[str, Any]]:
    """Scrape Yahoo search results via cloudscraper."""
    try:
        response = _scraper.get(
            "https://search.yahoo.com/search",
            params={"p": query, "n": num_results},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        results: List[Dict[str, Any]] = []
        for div in soup.select("div.algo-sr") + soup.select("div.dd.algo") + soup.select("div.Sr"):
            a_tag = div.find("a", href=True)
            if not a_tag:
                continue
            raw_url = a_tag["href"]
            # Yahoo wraps URLs in redirect
            parsed_qs = parse_qs(urlparse(raw_url).query)
            url = parsed_qs.get("RU", [raw_url])[0]
            if "yahoo.com" in url:
                continue
            title = a_tag.get_text(" ", strip=True)
            snippet_tag = div.find("p") or div.find("span", class_="fc-falcon")
            body = snippet_tag.get_text(" ", strip=True) if snippet_tag else ""
            results.append({"title": title, "body": body[:320], "href": url, "search_engine": "yahoo"})
            if len(results) >= num_results:
                break
        logger.info("Found %s Yahoo results for query: %s", len(results), query)
        return results
    except Exception as exc:
        logger.debug("Yahoo search failed for '%s': %s", query, exc)
        return []


def search_with_yandex(query: str, num_results: int = 5) -> List[Dict[str, Any]]:
    """Scrape Yandex search results via cloudscraper."""
    try:
        response = _scraper.get(
            "https://yandex.com/search/",
            params={"text": query, "numdoc": num_results, "lang": "en"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        results: List[Dict[str, Any]] = []
        for item in soup.select("li.serp-item"):
            a_tag = item.find("a", href=True)
            if not a_tag:
                continue
            url = a_tag["href"]
            if "yandex." in url:
                continue
            title = a_tag.get_text(" ", strip=True)
            snippet_tag = item.find("span", class_="OrganicTextContentSpan") or item.find("div", class_="text-container")
            body = snippet_tag.get_text(" ", strip=True) if snippet_tag else ""
            results.append({"title": title, "body": body[:320], "href": url, "search_engine": "yandex"})
            if len(results) >= num_results:
                break
        logger.info("Found %s Yandex results for query: %s", len(results), query)
        return results
    except Exception as exc:
        logger.debug("Yandex search failed for '%s': %s", query, exc)
        return []


# ── Multi-engine search: query ALL engines, merge results ──
# DDG is primary, others are reserve fallbacks.
# Google requires ENABLE_GOOGLE_SEARCH=true in env.
# Bing/Yahoo/Yandex scrapers may need selector updates over time.
SEARCH_ENGINE_ORDER = [
    ("ddg", search_with_ddgs),
    ("bing", search_with_bing),
    ("yahoo", search_with_yahoo),
    ("yandex", search_with_yandex),
    ("google", search_with_google),
]


def multi_engine_search(query: str, num_results: int = 8, timelimit: Optional[str] = None) -> List[Dict[str, Any]]:
    """Query ALL available search engines and merge deduplicated results."""
    all_results: List[Dict[str, Any]] = []
    seen_urls: set = set()

    for engine_name, search_fn in SEARCH_ENGINE_ORDER:
        try:
            if engine_name == "ddg":
                raw = search_fn(query, num_results=num_results, timelimit=timelimit)
            elif engine_name == "google":
                if not _google_is_available():
                    continue
                raw = search_fn(query, num_results=num_results)
            else:
                raw = search_fn(query, num_results=num_results)
        except Exception as exc:
            logger.debug("Engine %s failed: %s", engine_name, exc)
            continue

        added = 0
        for r in raw:
            url = r.get("href", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            r.setdefault("search_engine", engine_name)
            all_results.append(r)
            added += 1

        logger.info("Engine '%s': +%d results (total %d)", engine_name, added, len(all_results))

    return all_results


def _search_with_exa(query: str, include_domains: List[str], num_results: int = 3) -> Dict[str, Any]:
    if not EXA_API_KEY:
        return {"answer": "", "results": []}

    # ── Method 1: exa-py SDK (preferred) ──
    if ExaClient is not None:
        try:
            exa = ExaClient(api_key=EXA_API_KEY)
            kwargs: Dict[str, Any] = {
                "query": query,
                "num_results": num_results,
                "text": {"max_characters": 900},
                "type": "auto",
            }
            if include_domains:
                kwargs["include_domains"] = include_domains
            response = exa.search_and_contents(**kwargs)
            results: List[Dict[str, Any]] = []
            for item in response.results:
                snippet = (getattr(item, "text", "") or "").strip()
                if not snippet:
                    highlights = getattr(item, "highlights", None) or []
                    if isinstance(highlights, list):
                        snippet = " ".join(str(h).strip() for h in highlights if h).strip()
                results.append({
                    "title": (getattr(item, "title", "") or "").strip(),
                    "body": snippet,
                    "href": (getattr(item, "url", "") or "").strip(),
                    "search_engine": "exa",
                })
            return {"answer": "", "results": results}
        except Exception as exc:
            logger.warning("Exa SDK search failed for query '%s': %s", query, exc)

    # ── Method 2: raw HTTP fallback ──
    payload: Dict[str, Any] = {
        "query": query,
        "numResults": num_results,
        "contents": {"text": {"maxCharacters": 900}},
    }
    if include_domains:
        payload["includeDomains"] = include_domains

    try:
        response = requests.post(
            "https://api.exa.ai/search",
            headers={
                "x-api-key": EXA_API_KEY,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.warning("Exa HTTP search failed for query '%s': %s", query, exc)
        return {"answer": "", "results": []}

    results = []
    for item in data.get("results", []):
        snippet = (item.get("text") or "").strip()
        if not snippet:
            highlights = item.get("highlights") or []
            if isinstance(highlights, list):
                snippet = " ".join(str(highlight).strip() for highlight in highlights if highlight).strip()
        results.append({
            "title": (item.get("title") or "").strip(),
            "body": snippet,
            "href": (item.get("url") or "").strip(),
            "search_engine": "exa",
        })

    return {"answer": "", "results": results}


def _search_with_tavily(query: str, include_domains: List[str], num_results: int = 3) -> Dict[str, Any]:
    if not TAVILY_API_KEY or TavilyClient is None:
        return {"answer": "", "results": []}

    client = TavilyClient(api_key=TAVILY_API_KEY)
    try:
        response = client.search(
            query=query,
            topic="general",
            search_depth="advanced",
            max_results=num_results,
            include_domains=include_domains or None,
            include_answer=True,
            include_raw_content=False,
        )
    except Exception as exc:
        logger.warning("Tavily analysis search failed for query '%s': %s", query, exc)
        return {"answer": "", "results": []}

    results: List[Dict[str, Any]] = []
    for item in response.get("results", []):
        results.append(
            {
                "title": (item.get("title") or "").strip(),
                "body": (item.get("content") or item.get("snippet") or "").strip(),
                "href": (item.get("url") or "").strip(),
                "search_engine": "tavily",
            }
        )

    answer = (response.get("answer") or "").strip()
    return {"answer": answer, "results": results}


def _analysis_providers() -> List[str]:
    provider = SEARCH_ANALYSIS_PROVIDER
    if provider == "exa":
        return ["exa"]
    if provider == "tavily":
        return ["tavily"]
    return ["exa", "tavily"]


def _merge_analysis_results(query: str, include_domains: List[str]) -> Dict[str, Any]:
    merged: List[Dict[str, Any]] = []
    seen_urls = set()
    answers: List[str] = []

    for provider in _analysis_providers():
        payload = _search_with_exa(query, include_domains, SEARCH_ANALYSIS_RESULTS_PER_QUERY) if provider == "exa" else _search_with_tavily(query, include_domains, SEARCH_ANALYSIS_RESULTS_PER_QUERY)
        answer = (payload.get("answer") or "").strip()
        if answer:
            answers.append(f"{provider}: {answer}")

        for result in payload.get("results") or []:
            url = result.get("href", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            merged.append(result)

    return {"answers": answers, "results": merged}


def _collect_analysis_sources(
    entity: str,
    discipline: str,
    stat_type: str,
    context_terms: Optional[str],
    sites: List[str],
    max_queries: int = 2,
) -> Dict[str, Any]:
    """Call AI search engines (Exa/Tavily) for enrichment. Limited to max_queries per entity."""
    snippets: List[Dict[str, Any]] = []
    answers: List[str] = []
    used_engines = set()
    normalized_answers = set()
    queries_made = 0

    if not sites:
        return {"answers": [], "snippets": [], "used_engines": []}

    for site in sites[:2]:
        if queries_made >= max_queries:
            break
        queries = _build_site_queries(entity, site, stat_type, context_terms)
        for query in queries[:1]:
            if queries_made >= max_queries:
                break
            queries_made += 1
            logger.info("AI search query %d/%d: %s", queries_made, max_queries, query)
            payload = _merge_analysis_results(query, [site])

            for answer in payload.get("answers", []):
                key = answer.lower()
                if key in normalized_answers:
                    continue
                normalized_answers.add(key)
                answers.append(answer)

            for result in payload.get("results", []):
                url = result.get("href", "")
                title = result.get("title", "")
                body = result.get("body", "")
                if not _is_result_valid(entity, title, body, "", url):
                    continue

                engine = result.get("search_engine", "unknown")
                used_engines.add(engine)
                snippets.append(
                    {
                        "site": site,
                        "query": query,
                        "search_engine": engine,
                        "title": title,
                        "body": (body or "")[:260],
                        "href": url,
                    }
                )
                if len(snippets) >= SEARCH_ANALYSIS_MAX_SNIPPETS:
                    break

            if len(snippets) >= SEARCH_ANALYSIS_MAX_SNIPPETS:
                break
        if len(snippets) >= SEARCH_ANALYSIS_MAX_SNIPPETS:
            break

    logger.info("AI search done: %d queries, %d snippets found", queries_made, len(snippets))
    return {
        "answers": answers[:4],
        "snippets": snippets,
        "used_engines": sorted(used_engines),
    }


_DISCIPLINE_SEARCH_LABEL = {
    "football": "football soccer",
    "tennis": "tennis ATP WTA",
    "table_tennis": "table tennis",
    "hockey": "hockey NHL KHL",
    "basketball": "basketball NBA",
    "volleyball": "volleyball",
    "mma": "MMA UFC",
    "boxing": "boxing",
    "cs2": "CS2 esports",
    "dota2": "Dota 2 esports",
    "lol": "League of Legends esports",
    "valorant": "Valorant esports",
}


def collect_validated_sources(
    entity: str,
    discipline: str,
    stat_type: str,
    *,
    min_sources: int = 2,
    timelimit: str = "m",
    context_terms: Optional[str] = None,
) -> Dict[str, Any]:
    all_sites = DISCIPLINE_SOURCE_CONFIG.get(discipline, [])
    trusted_domains = {entry["site"] for entry in all_sites}
    validated_sources: List[Dict[str, Any]] = []
    unvalidated_results: List[Dict[str, Any]] = []
    seen_urls: set = set()

    discipline_label = _DISCIPLINE_SEARCH_LABEL.get(discipline, discipline)
    context_suffix = f" {context_terms}" if context_terms else ""

    def _validate_and_collect(results: List[Dict[str, Any]]) -> None:
        """Validate results and add to validated_sources / unvalidated_results."""
        for result in results:
            if len(validated_sources) >= min_sources:
                return
            url = result.get("href", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            title = result.get("title", "")
            body = result.get("body", "")
            if not _is_result_valid(entity, title, body, "", url):
                unvalidated_results.append(result)
                continue
            excerpt = _fetch_page_excerpt(url, entity) if url else ""
            source = _extract_source(url)
            is_trusted = any(domain in url for domain in trusted_domains)
            validated_sources.append({
                "site": source,
                "source": source,
                "search_engine": result.get("search_engine", "unknown"),
                "title": title,
                "body": body[:260],
                "excerpt": excerpt[:640],
                "href": url,
                "validated": True,
                "trusted_domain": is_trusted,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            })

    # ── Бюджет запросов на участника: max 2 бесплатных + max 2 AI = max 4 ──
    MAX_FREE_QUERIES = 2
    MAX_AI_QUERIES = 2

    # ── Phase 1: broad search across ALL free engines (free query 1/2) ──
    free_queries_used = 0
    broad_query = f"{entity} {discipline_label} {stat_type}{context_suffix}"
    free_queries_used += 1
    logger.info("Phase 1 — free query %d/%d (broad): %s", free_queries_used, MAX_FREE_QUERIES, broad_query)
    broad_results = multi_engine_search(broad_query, num_results=10, timelimit=timelimit)

    # Sort broad results: trusted domains first
    broad_results.sort(
        key=lambda r: not any(d in r.get("href", "") for d in trusted_domains)
    )
    _validate_and_collect(broad_results)
    logger.info("After Phase 1: %d validated for '%s'", len(validated_sources), entity)

    # ── Phase 2: targeted site: query (free query 2/2) — only if Phase 1 insufficient ──
    if len(validated_sources) < min_sources and free_queries_used < MAX_FREE_QUERIES:
        sites_to_query = _get_sites_for_query(discipline, entity, context_terms)
        for site in sites_to_query[:1]:
            if len(validated_sources) >= min_sources:
                break
            if free_queries_used >= MAX_FREE_QUERIES:
                break
            free_queries_used += 1
            site_query = f"{entity} {stat_type}{context_suffix} site:{site}"
            logger.info("Phase 2 — free query %d/%d (site): %s", free_queries_used, MAX_FREE_QUERIES, site_query)
            try:
                raw = search_with_ddgs(site_query, num_results=3, timelimit=timelimit)
            except Exception:
                raw = []
            for r in raw:
                r.setdefault("search_engine", "site_search")
            _validate_and_collect(raw)
        logger.info("After Phase 2: %d validated for '%s'", len(validated_sources), entity)

    logger.info("Free engines done: %d/%d queries used, %d validated sources for '%s'",
                free_queries_used, MAX_FREE_QUERIES, len(validated_sources), entity)

    # ── Phase 3: AI search (Exa/Tavily) — fallback, max 2 queries ──
    analysis_sources: Dict[str, Any] = {"answers": [], "snippets": [], "used_engines": []}
    if len(validated_sources) < min_sources:
        if EXA_API_KEY or TAVILY_API_KEY:
            logger.info("Phase 3 — free insufficient (%d/%d), calling AI search (max %d) for '%s'",
                         len(validated_sources), min_sources, MAX_AI_QUERIES, entity)
            analysis_sources = _collect_analysis_sources(
                entity, discipline, stat_type, context_terms,
                [e["site"] for e in all_sites],
                max_queries=MAX_AI_QUERIES,
            )
        else:
            logger.info("Phase 3 — free insufficient but no AI keys configured")
    else:
        logger.info("Phase 3 — free sufficient (%d/%d), skipping AI search for '%s'",
                     len(validated_sources), min_sources, entity)

    # ── Fallback: if still nothing validated, take best-matching raw results ──
    if not validated_sources and unvalidated_results:
        logger.info("Fallback: scoring %d unvalidated results for '%s'",
                     len(unvalidated_results), entity)
        entity_tokens = _normalize_tokens(entity)
        scored: List[tuple] = []
        for result in unvalidated_results:
            url = result.get("href", "")
            title = result.get("title", "")
            body = result.get("body", "")
            url_text = urlparse(url).path.replace("-", " ").replace("_", " ") if url else ""
            haystack = f"{title} {body} {url_text}".lower()
            match_count = sum(1 for t in entity_tokens if t in haystack)
            if match_count > 0:  # at least 1 token matches — not completely random
                scored.append((match_count, result))
        scored.sort(key=lambda x: x[0], reverse=True)
        for _, result in scored[:min_sources]:
            url = result.get("href", "")
            title = result.get("title", "")
            body = result.get("body", "")
            excerpt = _fetch_page_excerpt(url, entity) if url else ""
            source = _extract_source(url)
            is_trusted = any(domain in url for domain in trusted_domains)
            validated_sources.append({
                "site": source,
                "source": source,
                "search_engine": result.get("search_engine", "unknown"),
                "title": title,
                "body": body[:260],
                "excerpt": excerpt[:640],
                "href": url,
                "validated": False,
                "trusted_domain": is_trusted,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            })

    enough = len(validated_sources) >= min_sources
    return {
        "entity": entity,
        "discipline": discipline,
        "stat_type": stat_type,
        "min_sources": min_sources,
        "freshness_window": timelimit,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "validated_sources": validated_sources,
        "analysis_sources": analysis_sources,
        "validated_count": len(validated_sources),
        "enough_sources": enough,
        "status": "validated" if enough else "insufficient_sources",
    }


def validate_match_request(match_text: str, date_text: str, discipline: str) -> Dict[str, Any]:
    sides = split_match_text(match_text)
    if len(sides) != 2:
        return {
            "status": "invalid_match",
            "match": None,
            "report": "Валидация: неверный формат матча.",
        }

    discipline_key = _normalize_validation_discipline_key(discipline)
    if discipline_key not in DISCIPLINE_SOURCE_CONFIG:
        return {
            "status": "unsupported_discipline",
            "match": None,
            "report": f"Валидация: дисциплина '{discipline}' не поддерживается для веб-проверки.",
        }

    participant_reports = []
    for side in sides:
        participant_reports.append(
            collect_validated_sources(
                side,
                discipline_key,
                "official team player roster ranking profile recent results current season",
                min_sources=1,
                timelimit="m",
                context_terms=None,
            )
        )

    if any(report.get("validated_count", 0) < 1 for report in participant_reports):
        report_blocks = [format_validated_report(report) for report in participant_reports]
        return {
            "status": "insufficient_sources",
            "match": None,
            "report": "\n\n".join(report_blocks),
            "validated_count": sum(report.get("validated_count", 0) for report in participant_reports),
        }

    normalized_date = date_text.strip() if date_text else "дата не указана"
    report_lines = [
        f"Валидация 1 контура: участники подтверждены для дисциплины {discipline_key}.",
        "Дата матча используется из ввода пользователя.",
        "",
    ]
    report_lines.extend(format_validated_report(report) for report in participant_reports)

    match_payload = {
        "sport": discipline_key,
        "home": sides[0],
        "away": sides[1],
        "date": normalized_date,
        "league": "user input",
        "user_discipline": discipline,
    }

    return {
        "status": "validated",
        "match": match_payload,
        "report": "\n\n".join(report_lines),
        "validated_count": sum(report.get("validated_count", 0) for report in participant_reports),
    }


def format_validated_report(report: Dict[str, Any]) -> str:
    if not report["validated_sources"]:
        return (
            f"Валидация: недостаточно данных для {report['entity']}. "
            f"Проверено источников: 0. Окно свежести: {report['freshness_window']}."
        )

    header = [
        f"Валидация: {report['status']}",
        f"Подтверждено источников: {report['validated_count']}",
        f"Минимум источников: {report.get('min_sources', 2)}",
        f"Окно свежести поиска: {report['freshness_window']}",
        f"Проверено: {report['checked_at']}",
    ]

    blocks = []
    for index, source in enumerate(report["validated_sources"], start=1):
        blocks.append(
            "\n".join(
                [
                    f"Источник {index}: {source['source']}",
                    f"Заголовок: {source['title']}",
                    f"Поисковик: {source['search_engine']}",
                    f"Сниппет: {source['body']}",
                    f"Выжимка со страницы: {source['excerpt'] or 'нет доступного текста'}",
                    f"Ссылка: {source['href']}",
                ]
            )
        )

    analysis = report.get("analysis_sources") or {}
    analysis_answers = analysis.get("answers") or []
    analysis_snippets = analysis.get("snippets") or []
    analysis_engines = ", ".join(analysis.get("used_engines") or []) or "нет"

    analysis_lines = [
        "",
        f"Аналитический поиск (Exa/Tavily): {analysis_engines}",
    ]
    for answer in analysis_answers:
        analysis_lines.append(f"Ответ движка: {answer}")
    for idx, snippet in enumerate(analysis_snippets, start=1):
        analysis_lines.extend(
            [
                f"Аналитика {idx}: {snippet['search_engine']} ({snippet['site']})",
                f"Query: {snippet['query']}",
                f"Заголовок: {snippet['title']}",
                f"Сниппет: {snippet['body']}",
                f"Ссылка: {snippet['href']}",
            ]
        )

    return "\n".join(header + [""] + blocks + analysis_lines)


def _search(entity: str, discipline: str, stat_type: str, context_terms: Optional[str] = None) -> str:
    report = collect_validated_sources(
        entity,
        discipline,
        stat_type,
        min_sources=2,
        timelimit="w",
        context_terms=context_terms,
    )
    return format_validated_report(report)


def search_cs2_stats(team_name: str, context_terms: Optional[str] = None) -> str:
    return _search(team_name, "cs2", "lineup map pool pistol rounds rating 2.0 recent results", context_terms)


def search_dota_stats(team_name: str, context_terms: Optional[str] = None) -> str:
    return _search(team_name, "dota2", "hero meta pub stats stand-ins bracket recent results", context_terms)


def search_lol_stats(team_name: str, context_terms: Optional[str] = None) -> str:
    return _search(team_name, "lol", "gold per minute object control draft roster recent results", context_terms)


def search_valorant_stats(team_name: str, context_terms: Optional[str] = None) -> str:
    return _search(team_name, "valorant", "map stats agent stats lineup recent results", context_terms)


def search_football_stats(team_name: str, context_terms: Optional[str] = None) -> str:
    return _search(team_name, "football", "injuries suspensions lineups xg sca pressing player ratings recent results", context_terms)


def search_tennis_player(player_name: str, context_terms: Optional[str] = None) -> str:
    return _search(player_name, "tennis", "h2h surface fatigue first serve second serve recent matches", context_terms)


def search_table_tennis_player(player_name: str, context_terms: Optional[str] = None) -> str:
    return _search(player_name, "table_tennis", "ranking results equipment pips inverted style recent matches", context_terms)


def search_mma_fighter(fighter_name: str, context_terms: Optional[str] = None) -> str:
    return _search(fighter_name, "mma", "record reach gym striking accuracy takedown defense control time recent fight", context_terms)


def search_boxing_fighter(boxer_name: str, context_terms: Optional[str] = None) -> str:
    return _search(boxer_name, "boxing", "record titles ranking opposition recent fight", context_terms)


def search_basketball_team(team_name: str, context_terms: Optional[str] = None) -> str:
    return _search(team_name, "basketball", "pace offensive rating lineup injuries recent games", context_terms)


def search_hockey_team(team_name: str, context_terms: Optional[str] = None) -> str:
    return _search(team_name, "hockey", "roster transfers goals assists corsi fenwick khl europe recent games", context_terms)


def search_volleyball_team(team_name: str, context_terms: Optional[str] = None) -> str:
    return _search(team_name, "volleyball", "roster transfers leaders status recent matches", context_terms)
