"""Search and validation helpers for multi-source sports data collection."""

import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup
from services.name_normalizer import expand_context_terms, get_search_variants, normalize_entity_name, transliterate_text
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
REQUEST_TIMEOUT = 10
GOOGLE_SEARCH_URL = "https://www.google.com/search"
ENABLE_GOOGLE_SEARCH = os.getenv("ENABLE_GOOGLE_SEARCH", "false").strip().lower() in {"1", "true", "yes", "on"}
SEARCH_MAX_SITES = max(1, int(os.getenv("SEARCH_MAX_SITES", "4")))
SEARCH_RESULTS_PER_QUERY = max(1, int(os.getenv("SEARCH_RESULTS_PER_QUERY", "1")))
SEARCH_ENABLE_BROAD_WINDOW = os.getenv("SEARCH_ENABLE_BROAD_WINDOW", "false").strip().lower() in {"1", "true", "yes", "on"}
SEARCH_DDGS_BACKEND = os.getenv("SEARCH_DDGS_BACKEND", "duckduckgo")
SEARCH_REGION = os.getenv("SEARCH_REGION", "ru-ru")
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


def _google_is_available() -> bool:
    return ENABLE_GOOGLE_SEARCH and time.monotonic() >= _google_backoff_until


def _set_google_backoff() -> None:
    global _google_backoff_until
    _google_backoff_until = time.monotonic() + GOOGLE_BACKOFF_SECONDS


def _fetch_page_excerpt(url: str, entity: str) -> str:
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
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


def _is_result_valid(entity: str, title: str, body: str, excerpt: str) -> bool:
    haystack = f"{title} {body} {excerpt}".lower()
    entity_tokens = _normalize_tokens(entity)
    if not entity_tokens:
        return False

    matched = sum(1 for token in entity_tokens if token in haystack)
    if len(entity_tokens) == 1:
        return matched == 1
    return matched >= min(2, len(entity_tokens))


def search_with_ddgs(query: str, num_results: int = 5, timelimit: str = "m") -> List[Dict[str, Any]]:
    try:
        with DDGS(timeout=REQUEST_TIMEOUT) as ddgs:
            kwargs = {
                "max_results": num_results,
                "backend": SEARCH_DDGS_BACKEND,
                "region": SEARCH_REGION,
            }
            if timelimit:
                kwargs["timelimit"] = timelimit
            results = list(ddgs.text(query, **kwargs))
        logger.info("Found %s results for query: %s", len(results), query)
        return results
    except Exception as exc:
        if "No results found" in str(exc):
            logger.info("No DDG results for query: %s", query)
        else:
            logger.error("DDG search failed for query '%s': %s", query, exc)
        return []


def search_with_google(query: str, num_results: int = 5) -> List[Dict[str, Any]]:
    if not _google_is_available():
        logger.debug("Google search skipped for query '%s'", query)
        return []

    try:
        response = requests.get(
            GOOGLE_SEARCH_URL,
            params={"q": query, "hl": "en", "num": num_results},
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        results: List[Dict[str, Any]] = []

        for link in soup.select("a[href^='/url?q=']"):
            href = link.get("href", "")
            parsed = parse_qs(urlparse(href).query)
            url = parsed.get("q", [""])[0]
            if not url or "google.com" in url:
                continue

            title_node = link.find("h3")
            title = title_node.get_text(" ", strip=True) if title_node else link.get_text(" ", strip=True)
            parent_text = link.parent.get_text(" ", strip=True) if link.parent else ""
            results.append({
                "title": title,
                "body": parent_text[:320],
                "href": url,
                "search_engine": "google",
            })
            if len(results) >= num_results:
                break

        logger.info("Found %s Google results for query: %s", len(results), query)
        return results
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 429:
            logger.warning("Google search throttled, backing off for %s seconds", GOOGLE_BACKOFF_SECONDS)
            _set_google_backoff()
        logger.error("Google search failed for query '%s': %s", query, exc)
        return []
    except Exception as exc:
        logger.error("Google search failed for query '%s': %s", query, exc)
        return []


def _merge_search_results(query: str, timelimit: Optional[str]) -> List[Dict[str, Any]]:
    ddg_results = search_with_ddgs(query, num_results=SEARCH_RESULTS_PER_QUERY, timelimit=timelimit)
    for result in ddg_results:
        result.setdefault("search_engine", "duckduckgo")

    google_results = search_with_google(query, num_results=SEARCH_RESULTS_PER_QUERY)

    merged: List[Dict[str, Any]] = []
    seen_urls = set()
    for result in ddg_results + google_results:
        url = result.get("href", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        merged.append(result)
    return merged


def collect_validated_sources(
    entity: str,
    discipline: str,
    stat_type: str,
    *,
    min_sources: int = 2,
    timelimit: str = "m",
    context_terms: Optional[str] = None,
) -> Dict[str, Any]:
    sites = _get_sites_for_query(discipline, entity, context_terms)
    windows_to_try = [timelimit]
    if SEARCH_ENABLE_BROAD_WINDOW:
        windows_to_try.append(None)
    validated_sources: List[Dict[str, Any]] = []
    used_window = timelimit

    for window in windows_to_try:
        validated_sources = []
        used_window = window or "all"

        for site in sites:
            results: List[Dict[str, Any]] = []
            for query in _build_site_queries(entity, site, stat_type, context_terms):
                results = _merge_search_results(query, window or None)
                if results:
                    break

            best_match = None

            for result in results:
                url = result.get("href", "")
                source = _extract_source(url)
                excerpt = _fetch_page_excerpt(url, entity) if url else ""
                title = result.get("title", "")
                body = result.get("body", "")
                if not _is_result_valid(entity, title, body, excerpt):
                    continue

                best_match = {
                    "site": site,
                    "source": source,
                    "search_engine": result.get("search_engine", "unknown"),
                    "title": title,
                    "body": body[:260],
                    "excerpt": excerpt[:520],
                    "href": url,
                    "validated": True,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }
                break

            if best_match:
                validated_sources.append(best_match)
            if len(validated_sources) >= min_sources:
                break

        if len(validated_sources) >= min_sources:
            break

    return {
        "entity": entity,
        "discipline": discipline,
        "stat_type": stat_type,
        "freshness_window": used_window,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "validated_sources": validated_sources,
        "validated_count": len(validated_sources),
        "enough_sources": len(validated_sources) >= min_sources,
        "status": "validated" if len(validated_sources) >= min_sources else "insufficient_sources",
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
        f"Минимум источников: 2",
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

    return "\n".join(header + [""] + blocks)


def _search(entity: str, discipline: str, stat_type: str, context_terms: Optional[str] = None) -> str:
    report = collect_validated_sources(
        entity,
        discipline,
        stat_type,
        min_sources=2,
        timelimit="m",
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
