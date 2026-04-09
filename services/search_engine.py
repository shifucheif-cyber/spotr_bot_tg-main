"""Search and validation helpers for multi-source sports data collection.

Пайплайн данных:
1) validate_match_request() — DDG-валидация сущности/события.
2) collect_discipline_data() — сбор данных для анализа:
   Serper → Tavily/Exa → DDG (последний резерв).
   По 2 запроса на участника + 1 H2H.
3) collect_validated_sources() — legacy-каскад (DDG→Serper→Exa/Tavily),
   используется в validate_match_request.
"""


# --- Импорты и переменные окружения ---
import logging
import os
import re
import time
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import httpx
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
    DDGS = None

# --- API keys ---
EXA_API_KEY = os.getenv("EXA_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
SERPER_API_KEY = os.getenv("SERPER_API_KEY")

logger = logging.getLogger(__name__)
logger.info(f"[KEYS] EXA_API_KEY={'SET' if EXA_API_KEY else 'MISSING'}")
logger.info(f"[KEYS] TAVILY_API_KEY={'SET' if TAVILY_API_KEY else 'MISSING'}")
logger.info(f"[KEYS] SERPER_API_KEY={'SET' if SERPER_API_KEY else 'MISSING'}")


def format_validated_report(report: dict) -> str:
    """Форматирует отчет по валидированным источникам для вывода пользователю."""
    header = [
        f"Источники для: {report.get('entity', '')}",
        f"Дисциплина: {report.get('discipline', '')}",
        f"Тип статистики: {report.get('stat_type', '')}",
        f"Валидировано: {report.get('validated_count', 0)}",
    ]
    blocks = []
    for source in report.get("validated_sources", []):
        blocks.extend([
            f"Источник: {source['site']}",
            f"Заголовок: {source['title']}",
            f"Сниппет: {source['body']}",
            f"Выжимка со страницы: {source['excerpt'] or 'нет доступного текста'}",
            f"Ссылка: {source['href']}",
            "",
        ])
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
        analysis_lines.extend([
            f"Аналитика {idx}: {snippet['search_engine']} ({snippet['site']})",
            f"Query: {snippet['query']}",
            f"Заголовок: {snippet['title']}",
            f"Сниппет: {snippet['body']}",
            f"Ссылка: {snippet['href']}",
            "",
        ])
    return "\n".join(header + [""] + blocks + analysis_lines)




REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
REQUEST_TIMEOUT = 10
GOOGLE_BACKOFF_SECONDS = max(60, int(os.getenv("GOOGLE_BACKOFF_SECONDS", "900")))
SEARCH_ANALYSIS_PROVIDER = os.getenv("SEARCH_ANALYSIS_PROVIDER", "hybrid").strip().lower()
SEARCH_ANALYSIS_RESULTS_PER_QUERY = max(1, int(os.getenv("SEARCH_ANALYSIS_RESULTS_PER_QUERY", "2")))
SEARCH_ANALYSIS_MAX_SNIPPETS = max(1, int(os.getenv("SEARCH_ANALYSIS_MAX_SNIPPETS", "4")))
# Доп. запрос к Serper: новости, травмы, замены, форма, график (настраивается через .env)
SEARCH_SERP_SUPPLEMENT_TERMS = os.getenv(
    "SEARCH_SERP_SUPPLEMENT_TERMS",
    "news injury suspension lineup transfer substitution fatigue form schedule rumors preview",
).strip()
SEARCH_MAX_SITES = max(1, int(os.getenv("SEARCH_MAX_SITES", "4")))
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
        {"site": "flashscore.com", "label": "Flashscore Tennis", "focus": "live scores results h2h tennis rankings"},
        {"site": "sofascore.com", "label": "SofaScore Tennis", "focus": "tennis rankings h2h stats recent form"},
        {"site": "atptour.com", "label": "ATP Tour", "focus": "atp rankings stats player profile results"},
        {"site": "wtatennis.com", "label": "WTA", "focus": "wta rankings stats player profile results"},
    ],
    "table_tennis": [
        {"site": "ittf.com", "label": "ITTF", "focus": "official ranking major tournament results"},
        {"site": "tabletennis-guide.com", "label": "Table Tennis Guide", "focus": "equipment pips inverted style matchup"},
        {"site": "tt-rating.ru", "label": "TT Rating", "focus": "russian table tennis ratings results tournaments", "region": "ru"},
        {"site": "flashscore.com", "label": "Flashscore TT", "focus": "table tennis live scores results h2h"},
        {"site": "sofascore.com", "label": "SofaScore TT", "focus": "table tennis results rankings h2h stats"},
    ],
    "mma": [
        {"site": "aca-mma.com", "label": "ACA MMA", "focus": "russian league results fighter stats cards", "region": "ru"},
        {"site": "fighttime.ru", "label": "FightTime", "focus": "cis fighter rankings calendars russian mma news", "region": "ru"},
        {"site": "sherdog.com", "label": "Sherdog", "focus": "fight history reach gyms"},
        {"site": "ufcstats.com", "label": "UFC Stats", "focus": "striking accuracy takedown defense control time"},
        {"site": "tapology.com", "label": "Tapology", "focus": "mma record results upcoming bouts rankings gym"},
        {"site": "championat.com", "label": "Championat MMA", "focus": "mma news previews analysis results", "region": "ru"},
        {"site": "espn.com", "label": "ESPN MMA", "focus": "mma rankings schedule results analysis"},
    ],
    "boxing": [
        {"site": "boxrec.com", "label": "BoxRec", "focus": "verified record titles strength of opposition"},
        {"site": "allboxing.ru", "label": "AllBoxing", "focus": "russian professional boxing news results interviews", "region": "ru"},
        {"site": "tapology.com", "label": "Tapology", "focus": "boxing record results upcoming bouts rankings"},
        {"site": "ringtv.com", "label": "Ring Magazine", "focus": "boxing news rankings analysis previews"},
        {"site": "sports.ru", "label": "Sports.ru", "focus": "boxing news previews analysis results", "region": "ru"},
        {"site": "championat.com", "label": "Championat", "focus": "boxing news previews results analysis", "region": "ru"},
        {"site": "espn.com", "label": "ESPN Boxing", "focus": "boxing rankings schedule results analysis"},
    ],
    "hockey": [
        {"site": "khl.ru", "label": "KHL Official", "focus": "ice time distance shot speed faceoffs official stats", "region": "ru"},
        {"site": "allhockey.ru", "label": "AllHockey", "focus": "transfers insider news player condition locker room", "region": "ru"},
        {"site": "r-hockey.ru", "label": "R-Hockey", "focus": "player database youth leagues career history", "region": "ru"},
        {"site": "vfrhl.ru", "label": "VHL Official", "focus": "vhl standings results match protocols rosters", "region": "ru"},
        {"site": "championat.com", "label": "Championat", "focus": "hockey news previews analysis standings", "region": "ru"},
        {"site": "sport-express.ru", "label": "Sport Express", "focus": "hockey previews injuries lineups analysis", "region": "ru"},
        {"site": "eliteprospects.com", "label": "Elite Prospects", "focus": "rosters transfers goals assists"},
        {"site": "flashscore.com", "label": "Flashscore", "focus": "live scores h2h standings results"},
        {"site": "liveresult.ru", "label": "LiveResult", "focus": "khl vhl europe quick results", "region": "ru"},
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


def _normalize_tokens(text: str) -> List[str]:
    cleaned = re.sub(r"[^\w\s]", " ", text.lower(), flags=re.UNICODE)
    return [token for token in cleaned.split() if len(token) > 1]


def _extract_source(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return "unknown"


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

    extra_keywords = [
        "average total points last matches",
        "average total goals last matches",
        "recent head-to-head scores"
    ]
    for entity_variant in entity_variants[:3]:
        for context_variant in context_variants[:2]:
            tail = f" {context_variant}" if context_variant else ""
            queries.append(f"{entity_variant} {stat_type}{tail} site:{site}".strip())
        # Добавляем дополнительные поисковые запросы для тотала и head-to-head
        for kw in extra_keywords:
            queries.append(f"{entity_variant} {kw} site:{site}")

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


# Shared thread pool for sync-to-async bridge (avoids creating pool per call)
_sync_executor = None

def _get_sync_executor():
    global _sync_executor
    if _sync_executor is None:
        import concurrent.futures
        _sync_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    return _sync_executor

def _fetch_page_excerpt(url: str, entity: str) -> str:
    """Синхронная обёртка для совместимости с legacy collect_validated_sources."""
    try:
        asyncio.get_running_loop()
        # Already inside event loop — run in thread
        return _get_sync_executor().submit(asyncio.run, _fetch_page_excerpt_async(url, entity)).result()
    except RuntimeError:
        # No running loop — safe to use asyncio.run directly
        try:
            return asyncio.run(_fetch_page_excerpt_async(url, entity))
        except Exception as exc:
            logger.debug("Page fetch failed for %s: %s", url, exc)
            return ""
    except Exception as exc:
        logger.debug("Page fetch failed for %s: %s", url, exc)
        return ""


async def _fetch_page_excerpt_async(url: str, entity: str, max_chars: int = 2000) -> str:
    """Асинхронно скачивает страницу и извлекает текстовый фрагмент (до max_chars)."""
    if not url:
        return ""
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
            resp = await client.get(url, headers=REQUEST_HEADERS)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return ""
            soup = BeautifulSoup(resp.text[:50_000], "lxml")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
            entity_lower = entity.lower()
            text_lower = text.lower()
            idx = text_lower.find(entity_lower)
            if idx >= 0:
                start = max(0, idx - 200)
                return text[start:start + max_chars]
            return text[:max_chars]
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
    if DDGS is None:
        return []
    try:
        ddgs = DDGS()
        kwargs: Dict[str, Any] = {"max_results": num_results}
        if timelimit:
            kwargs["timelimit"] = timelimit
        raw = ddgs.text(query, **kwargs)
        if not raw:
            logger.info("DDG: 0 results for: %s", query)
            return []
        normalized: List[Dict[str, Any]] = []
        for item in raw:
            href = (item.get("href") or item.get("url") or item.get("link") or "").strip()
            if not href:
                continue
            normalized.append({
                "title": (item.get("title") or item.get("heading") or "")[:500],
                "body": (item.get("body") or item.get("snippet") or "")[:500],
                "href": href,
                "search_engine": "ddg",
            })
        logger.info("DDG: %d results for: %s", len(normalized), query)
        return normalized
    except Exception as exc:
        logger.debug("DDG failed for '%s': %s", query, exc)
    return []




async def search_with_serper(query: str, num_results: int = 5) -> List[Dict[str, Any]]:
    """Асинхронный Google search через Serper.dev API (httpx)."""
    if not SERPER_API_KEY:
        return []
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(
                    "https://google.serper.dev/search",
                    headers={
                        "X-API-KEY": SERPER_API_KEY,
                        "Content-Type": "application/json",
                    },
                    json={"q": query, "num": num_results},
                )
                response.raise_for_status()
                data = response.json()
                results: List[Dict[str, Any]] = []
                for item in data.get("organic", []):
                    url = item.get("link", "")
                    if not url:
                        continue
                    results.append({
                        "title": item.get("title", ""),
                        "body": item.get("snippet", "")[:400],
                        "href": url,
                        "search_engine": "serper",
                    })
                    if len(results) >= num_results:
                        break
                logger.info("Serper: %d results for: %s", len(results), query)
                return results
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 and attempt == 0:
                logger.warning(f"Serper 429 Rate Limit, retrying after 1s for '{query}'")
                import asyncio
                await asyncio.sleep(1)
                continue
            if exc.response.status_code in (404, 429):
                logger.warning(f"Serper HTTP error {exc.response.status_code} for '{query}'")
                return []
            logger.debug(f"Serper HTTP error for '{query}': {exc}")
            return []
        except httpx.TimeoutException:
            logger.warning(f"Serper timeout for '{query}'")
            return []
        except Exception as exc:
            logger.debug(f"Serper search failed for '{query}': {exc}")
            return []
    return []




async def _search_with_exa(query: str, include_domains: List[str], num_results: int = 3) -> Dict[str, Any]:
    if not EXA_API_KEY:
        return {"answer": "", "results": []}

    payload: Dict[str, Any] = {
        "query": query,
        "numResults": num_results,
        "contents": {"text": {"maxCharacters": 900}},
    }
    if include_domains:
        payload["includeDomains"] = include_domains

    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(
                    "https://api.exa.ai/search",
                    headers={
                        "x-api-key": EXA_API_KEY,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                break
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 and attempt == 0:
                logger.warning(f"Exa 429 Rate Limit, retrying after 1s for '{query}'")
                import asyncio
                await asyncio.sleep(1)
                continue
            if exc.response.status_code in (404, 429):
                logger.warning(f"Exa HTTP error {exc.response.status_code} for '{query}'")
                return {"answer": "", "results": []}
            logger.debug(f"Exa HTTP error for '{query}': {exc}")
            return {"answer": "", "results": []}
        except httpx.TimeoutException:
            logger.warning(f"Exa timeout for '{query}'")
            return {"answer": "", "results": []}
        except Exception as exc:
            logger.warning(f"Exa HTTP search failed for query '{query}': {exc}")
            return {"answer": "", "results": []}
    else:
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


async def _search_with_tavily(query: str, include_domains: List[str], num_results: int = 3) -> Dict[str, Any]:
    if not TAVILY_API_KEY:
        return {"answer": "", "results": []}

    url = "https://api.tavily.com/search"
    payload = {
        "query": query,
        "topic": "general",
        "search_depth": "advanced",
        "max_results": num_results,
        "include_domains": include_domains or None,
        "include_answer": True,
        "include_raw_content": False,
    }
    headers = {
        "Authorization": f"Bearer {TAVILY_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 429):
            logger.warning(f"Tavily HTTP error {exc.response.status_code} for '{query}'")
            return {"answer": "", "results": []}
        logger.debug(f"Tavily HTTP error for '{query}': {exc}")
        return {"answer": "", "results": []}
    except httpx.TimeoutException:
        logger.warning(f"Tavily timeout for '{query}'")
        return {"answer": "", "results": []}
    except Exception as exc:
        logger.debug(f"Tavily search failed for '{query}': {exc}")
        return {"answer": "", "results": []}

    results: List[Dict[str, Any]] = []
    for item in data.get("results", []):
        results.append(
            {
                "title": (item.get("title") or "").strip(),
                "body": (item.get("content") or item.get("snippet") or "").strip(),
                "href": (item.get("url") or "").strip(),
                "search_engine": "tavily",
            }
        )

    answer = (data.get("answer") or "").strip()
    return {"answer": answer, "results": results}


def _analysis_providers() -> List[str]:
    provider = SEARCH_ANALYSIS_PROVIDER
    if provider == "exa":
        return ["exa"]
    if provider == "tavily":
        return ["tavily"]
    return ["exa", "tavily"]


async def _merge_analysis_results(query: str, include_domains: List[str]) -> Dict[str, Any]:
    merged: List[Dict[str, Any]] = []
    seen_urls = set()
    answers: List[str] = []

    for provider in _analysis_providers():
        payload = (
            await _search_with_exa(query, include_domains, SEARCH_ANALYSIS_RESULTS_PER_QUERY)
            if provider == "exa"
            else await _search_with_tavily(query, include_domains, SEARCH_ANALYSIS_RESULTS_PER_QUERY)
        )
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


async def _collect_analysis_sources(
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

    # --- Обязательные поисковые ключи для H2H и тоталов ---
    extra_queries = []
    if entity and context_terms:
        # Предполагаем, что context_terms содержит "vs" и обе команды
        h2h_query = f"{context_terms} last 5 matches scores and head-to-head"
        extra_queries.append(h2h_query)
    if entity:
        # Для тоталов — подбираем ключ по дисциплине
        avg_total = "average goals per match last 10 games"
        if discipline == "basketball":
            avg_total = "average points per match last 10 games"
        elif discipline in ("mma", "boxing"):
            avg_total = "average rounds per match last 10 fights"
        elif discipline in ("tennis", "table_tennis", "volleyball"):
            avg_total = "average games per match last 10 matches"
        extra_queries.append(f"{entity} {avg_total}")

    for site in sites[:2]:
        if queries_made >= max_queries:
            break
        queries = _build_site_queries(entity, site, stat_type, context_terms)
        # Добавляем обязательные queries
        queries = queries[:1] + extra_queries
        for query in queries:
            if queries_made >= max_queries:
                break
            queries_made += 1
            logger.info("AI search query %d/%d: %s", queries_made, max_queries, query)
            payload = await _merge_analysis_results(query, [site])

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
    "football": "football soccer UEFA EPL La Liga Serie A Bundesliga",
    "tennis": "tennis ATP WTA ITF",
    "table_tennis": "table tennis ITTF WTT",
    "hockey": "hockey KHL VHL MHL NHL SHL",
    "basketball": "basketball NBA Euroleague VTB",
    "volleyball": "volleyball CEV SuperLiga",
    "mma": "MMA UFC Bellator PFL",
    "boxing": "boxing WBA WBC IBF WBO",
    "cs2": "CS2 Counter-Strike esports HLTV",
    "dota2": "Dota 2 esports DPC",
    "lol": "League of Legends esports LCK LEC LCS",
    "valorant": "Valorant esports VCT",
}


def collect_validated_sources(
    entity: str,
    discipline: str,
    stat_type: str,
    *,
    min_sources: int = 2,
    timelimit: str = "m",
    context_terms: Optional[str] = None,
    region: Optional[str] = None,
) -> Dict[str, Any]:
    analysis_sources = {}
    logger.info(f"[VALIDATE] Старт: entity={entity}, discipline={discipline}, stat_type={stat_type}, region={region}, min_sources={min_sources}")
    all_sites = DISCIPLINE_SOURCE_CONFIG.get(discipline, [])
    trusted_domains = {entry["site"] for entry in all_sites}
    # Приоритизация источников по региону с fallback
    fallback_attempted = False
    def get_ordered_entries(region):
        if region == "ru":
            ordered = [entry for entry in all_sites if entry.get("region") == "ru"]
            ordered.extend(entry for entry in all_sites if entry.get("region") != "ru")
        elif region == "intl":
            ordered = [entry for entry in all_sites if entry.get("region") != "ru"]
            ordered.extend(entry for entry in all_sites if entry.get("region") == "ru")
        else:
            ordered = all_sites
        return ordered
    all_sites = get_ordered_entries(region)
    validated_sources: List[Dict[str, Any]] = []
    unvalidated_results: List[Dict[str, Any]] = []
    seen_urls: set = set()

    discipline_label = _DISCIPLINE_SEARCH_LABEL.get(discipline, discipline)
    context_suffix = f" {context_terms}" if context_terms else ""

    def _validate_and_collect(results: List[Dict[str, Any]]) -> None:
        for result in results:
            if len(validated_sources) >= min_sources:
                return
            url = result.get("href", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            title = result.get("title", "")
            body = result.get("body", "")
            source = _extract_source(url)
            is_trusted = any(domain in url for domain in trusted_domains)
            # Доверенный домен ИЛИ совпадение токенов сущности в title/body
            entity_tokens = _normalize_tokens(entity)
            haystack = f"{title} {body}".lower()
            token_hits = sum(1 for t in entity_tokens if t in haystack)
            if is_trusted or token_hits >= 1:
                excerpt = _fetch_page_excerpt(url, entity) if url else ""
                validated_sources.append({
                    "site": source,
                    "source": source,
                    "search_engine": result.get("search_engine", "unknown"),
                    "title": title,
                    "body": body[:400],
                    "excerpt": excerpt[:1200],
                    "href": url,
                    "validated": True,
                    "trusted_domain": is_trusted,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                })
            else:
                unvalidated_results.append(result)

    def _enough_payload() -> Dict[str, Any]:
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
            "enough_sources": True,
            "status": "validated",
        }

    def _fallback_payload() -> Dict[str, Any]:
        """Fallback: если ничего не провалидировано — скорим сырые результаты по совпадению токенов."""
        if not validated_sources and unvalidated_results:
            logger.info("[VALIDATE] Fallback: scoring %d unvalidated results for '%s'", len(unvalidated_results), entity)
            entity_tokens = _normalize_tokens(entity)
            scored: List[tuple] = []
            for result in unvalidated_results:
                url = result.get("href", "")
                title = result.get("title", "")
                body = result.get("body", "")
                url_text = urlparse(url).path.replace("-", " ").replace("_", " ") if url else ""
                haystack = f"{title} {body} {url_text}".lower()
                match_count = sum(1 for t in entity_tokens if t in haystack)
                if match_count > 0:
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
                    "body": body[:400],
                    "excerpt": excerpt[:1200],
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

    # 1. DuckDuckGo — первичная проверка сущности в открытом вебе (валидация участника/команды)
    import asyncio
    async def _main_async():
        nonlocal all_sites, trusted_domains, fallback_attempted
        if DDGS is not None:
            ddg_query = f"{entity} {discipline_label} {stat_type}{context_suffix}"
            logger.info("[VALIDATE] DDG phase: %s", ddg_query)
            ddg_results = search_with_ddgs(
                ddg_query, num_results=max(6, min_sources + 4), timelimit=timelimit
            )
            _validate_and_collect(ddg_results)
            logger.info("[VALIDATE] After DDG: %d validated for '%s'", len(validated_sources), entity)

        if len(validated_sources) >= min_sources:
            logger.info("[VALIDATE] After DDG достаточно данных: %d", len(validated_sources))
            return _enough_payload()

        # 2. Serper — основной запрос (статистика / профиль) + при нехватке — доп. контекст (новости, травмы, форма)
        serper_primary = f"{entity} {discipline_label} {stat_type}{context_suffix}"
        logger.info("[VALIDATE] Serper primary: %s", serper_primary)
        serper_results = await search_with_serper(serper_primary, num_results=3)
        _validate_and_collect(serper_results)
        logger.info("[VALIDATE] After Serper primary: %d validated for '%s'", len(validated_sources), entity)

        if len(validated_sources) < min_sources and SEARCH_SERP_SUPPLEMENT_TERMS and SERPER_API_KEY:
            supplement_q = f"{entity} {discipline_label} {SEARCH_SERP_SUPPLEMENT_TERMS}{context_suffix}"
            logger.info("[VALIDATE] Serper supplement (news/form/injuries): %s", supplement_q)
            supplement_results = await search_with_serper(supplement_q, num_results=3)
            _validate_and_collect(supplement_results)

        if len(validated_sources) < min_sources and not fallback_attempted and region in ("ru", "intl"):
            logger.info("[VALIDATE] Serper regional fallback: alt region for trusted site order")
            fallback_attempted = True
            alt_region = "intl" if region == "ru" else "ru"
            all_sites = get_ordered_entries(alt_region)
            trusted_domains = {entry["site"] for entry in all_sites}
            serper_results = await search_with_serper(serper_primary, num_results=3)
            _validate_and_collect(serper_results)
            if len(validated_sources) < min_sources and SEARCH_SERP_SUPPLEMENT_TERMS and SERPER_API_KEY:
                supplement_q = f"{entity} {discipline_label} {SEARCH_SERP_SUPPLEMENT_TERMS}{context_suffix}"
                supplement_results = await search_with_serper(supplement_q, num_results=3)
                _validate_and_collect(supplement_results)
            logger.info("[VALIDATE] After regional Serper: %d validated for '%s'", len(validated_sources), entity)

        if len(validated_sources) >= min_sources:
            logger.info("[VALIDATE] После Serper достаточно данных: %d", len(validated_sources))
            return _enough_payload()

        # 3. Exa/Tavily — только если после DDG + Serper источников всё ещё мало
        if (EXA_API_KEY or TAVILY_API_KEY):
            logger.info(f"[VALIDATE] Exa/Tavily phase: entity={entity}, discipline={discipline}, stat_type={stat_type}, context_terms={context_terms}")
            # _collect_analysis_sources тоже должен быть асинхронным, если вызывает асинхронные поиски
            analysis_sources = await _collect_analysis_sources(
                entity, discipline, stat_type, context_terms,
                [e["site"] for e in all_sites],
                max_queries=2,
            )
            logger.info(f"[VALIDATE] Exa/Tavily вернул {len(analysis_sources.get('snippets', []))} snippets")
            for snip in analysis_sources.get("snippets", []):
                if len(validated_sources) >= min_sources:
                    break
                validated_sources.append({
                    "site": snip.get("site", "ai"),
                    "source": snip.get("site", "ai"),
                    "search_engine": snip.get("search_engine", "ai"),
                    "title": snip.get("title", ""),
                    "body": snip.get("body", "")[:400],
                    "excerpt": snip.get("body", "")[:1200],
                    "href": snip.get("href", ""),
                    "validated": True,
                    "trusted_domain": True,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                })
            logger.info(f"[VALIDATE] После Exa/Tavily: {len(validated_sources)} валидировано для '{entity}'")

        return _fallback_payload()

    try:
        asyncio.get_running_loop()
        # Inside event loop (e.g. aiogram) — run in thread
        return _get_sync_executor().submit(asyncio.run, _main_async()).result()
    except RuntimeError:
        return asyncio.run(_main_async())


def validate_match_request(match_text: str, date_text: str, discipline: str) -> Dict[str, Any]:
    sides = split_match_text(match_text)
    discipline_key = _normalize_validation_discipline_key(discipline)
    discipline_label = _DISCIPLINE_SEARCH_LABEL.get(discipline_key, discipline_key)

    if len(sides) < 2:
        return {
            "status": "insufficient_sources",
            "match": None,
            "report": "Укажите двух участников в формате «Команда А vs Команда Б» (или «против»).",
            "validated_count": 0,
        }

    event_note = ""
    if DDGS is not None:
        date_part = (date_text or "").strip()
        match_q = f"{sides[0]} vs {sides[1]} {date_part} {discipline_label} match preview".strip()
        ev_hits = search_with_ddgs(match_q, num_results=5, timelimit="m")
        if ev_hits:
            event_note = f"Событие (DDG): найдено {len(ev_hits)} ссылок по запросу матча.\n\n"
        else:
            event_note = (
                "Событие (DDG): по полному запросу мало ссылок — дальше валидация участников (DDG → Serper).\n\n"
            )

    participant_reports = []
    regions = []
    for side in sides:
        rep = collect_validated_sources(
            side,
            discipline_key,
            "official team player roster ranking profile recent results current season",
            min_sources=1,
            timelimit="m",
            context_terms=None,
        )
        participant_reports.append(rep)
        # Определяем регион для каждого участника по источникам
        region = None
        for src in rep.get("validated_sources", []):
            # Используем region из DISCIPLINE_SOURCE_CONFIG
            for entry in DISCIPLINE_SOURCE_CONFIG.get(discipline_key, []):
                if src.get("site") == entry["site"] and entry.get("region") == "ru":
                    region = "ru"
                    break
            if not region:
                region = "intl"
        regions.append(region)

    if any(report.get("validated_count", 0) < 1 for report in participant_reports):
        report_blocks = [format_validated_report(report) for report in participant_reports]
        return {
            "status": "insufficient_sources",
            "match": None,
            "report": "\n\n".join(report_blocks),
            "validated_count": sum(report.get("validated_count", 0) for report in participant_reports),
        }

    region = "ru" if regions.count("ru") >= regions.count("intl") else "intl"
    normalized_date = date_text.strip() if date_text else "дата не указана"
    report_lines = [
        event_note,
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
        "region": region,
    }

    return {
        "status": "validated",
        "match": match_payload,
        "region": region,
        "report": "\n\n".join(report_lines),
        "validated_count": sum(report.get("validated_count", 0) for report in participant_reports),
    }


# ── Проверка минимальных данных ──

# Маппинг required_data ключей на regex-паттерны для обнаружения в тексте
_REQUIRED_DATA_PATTERNS = {
    "form": r"форм[аы]|form\b|серия|streak|последни[еx]|recent|win\b|loss|побед|поражен|результат|result",
    "h2h": r"h2h|очн[ыеая]|head.to.head|личн[ыеая]\s*встреч|face.?off",
    "injuries": r"травм|injur|дисквал|suspend|отсутств|absent|miss(?:ing)?|выбы[лв]",
    "ranking": r"рейтинг|ranking|seed|посев|position|ATP|WTA|ITTF|HLTV",
    "record": r"рекорд|record|\d+-\d+|побед.*поражен|wins?.*loss",
    "striking": r"striking|удар|accuracy|точност|punch|significant.strikes",
    "reach": r"reach|размах|рук|антропометр|height.*weight|рост.*вес",
    "roster": r"состав|roster|lineup|ростер|игрок|player|team.comp",
}


def check_required_data(
    collected_text: str,
    required_keys: List[str],
    discipline: str = "",
) -> Dict[str, Any]:
    """Проверяет наличие обязательных данных в собранном тексте.

    Returns:
        {"satisfied": bool, "missing": list[str], "found": list[str]}
    """
    if not collected_text or not required_keys:
        return {"satisfied": not required_keys, "missing": list(required_keys), "found": []}

    text_lower = collected_text.lower()
    found = []
    missing = []
    for key in required_keys:
        pattern = _REQUIRED_DATA_PATTERNS.get(key, re.escape(key))
        if re.search(pattern, text_lower):
            found.append(key)
        else:
            missing.append(key)

    return {"satisfied": len(missing) == 0, "missing": missing, "found": found}


# ── Новый пайплайн: collect_discipline_data ──

async def collect_discipline_data(
    participants: List[str],
    discipline: str,
    match_context: Optional[Dict[str, Any]] = None,
) -> str:
    """Собирает данные для анализа матча.

    Flow: Serper (min query) → Serper (max query) → check required_data →
          если missing → Tavily/Exa целевыми запросами → DDG fallback если Serper недоступен.
    По 2 запроса на участника + 1 H2H.

    Args:
        participants: список участников (2 элемента).
        discipline: ключ дисциплины из DISCIPLINE_CONFIG.
        match_context: {"date": ..., "league": ..., "sport": ..., "home": ..., "away": ...,
                        "pre_validated_sources": [...]}

    Returns:
        Форматированный текстовый отчёт для LLM.
    """
    from services.discipline_config import get_config, get_search_queries, get_h2h_query

    config = get_config(discipline)
    if not config:
        logger.warning("[COLLECT] Нет конфига для дисциплины: %s", discipline)
        return f"Дисциплина '{discipline}' не поддерживается."

    # Определяем язык запросов
    context_str = " ".join(participants) + " " + (match_context or {}).get("league", "")
    is_russian = _should_prefer_russian_sources(participants[0], context_str, discipline)

    all_results: Dict[str, List[Dict[str, Any]]] = {}
    seen_urls: set = set()

    # Учитываем данные валидации если переданы
    pre_validated = (match_context or {}).get("pre_validated_sources", [])
    if pre_validated:
        for src in pre_validated:
            url = src.get("href", "")
            if url:
                seen_urls.add(url)

    async def _search_primary(query: str, label: str, num: int = 5) -> List[Dict[str, Any]]:
        """Serper (primary) → DDG (fallback если Serper недоступен)."""
        results: List[Dict[str, Any]] = []

        # 1) Serper
        if SERPER_API_KEY:
            serper_res = await search_with_serper(query, num_results=num)
            for r in serper_res:
                url = r.get("href", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    results.append(r)
            if results:
                logger.info("[COLLECT] %s: Serper → %d результатов", label, len(results))
                return results

        # 2) DDG fallback (только если Serper недоступен)
        if DDGS is not None:
            ddg_res = search_with_ddgs(query, num_results=num, timelimit="m")
            for r in ddg_res:
                url = r.get("href", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    results.append(r)
            if results:
                logger.info("[COLLECT] %s: DDG fallback → %d результатов", label, len(results))

        return results

    async def _search_extended(
        entity: str, missing_keys: List[str], num: int = 4,
    ) -> List[Dict[str, Any]]:
        """Tavily/Exa — целевые запросы по недостающим required_data ключам."""
        if not (TAVILY_API_KEY or EXA_API_KEY):
            return []

        results: List[Dict[str, Any]] = []
        sites = [e["site"] for e in DISCIPLINE_SOURCE_CONFIG.get(discipline, [])]

        # Генерируем целевой запрос по missing ключам
        key_phrases = {
            "form": "форма результаты последние матчи" if is_russian else "form results recent matches",
            "h2h": "очные встречи h2h статистика" if is_russian else "head to head h2h stats",
            "injuries": "травмы дисквалификации отсутствующие" if is_russian else "injuries suspensions absent",
            "ranking": "рейтинг позиция" if is_russian else "ranking position seed",
            "record": "рекорд победы поражения" if is_russian else "record wins losses",
            "striking": "striking accuracy ударная статистика" if is_russian else "striking accuracy stats",
            "reach": "антропометрия рост вес размах рук" if is_russian else "reach height weight measurements",
            "roster": "состав ростер игроки" if is_russian else "roster lineup players",
        }
        missing_phrase = " ".join(key_phrases.get(k, k) for k in missing_keys)
        query = f"{entity} {missing_phrase}"

        merged = await _merge_analysis_results(query, sites[:4])
        for r in merged.get("results", []):
            url = r.get("href", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                results.append(r)

        if results:
            logger.info("[COLLECT] %s: Extended (Tavily/Exa) → %d результатов для [%s]",
                        entity, len(results), ", ".join(missing_keys))
        return results

    # ── Сбор данных по участникам ──
    match_date = (match_context or {}).get("date", "")
    required_keys = config.get("required_data", [])

    for participant in participants:
        queries = get_search_queries(config, participant, discipline, is_russian)
        participant_results: List[Dict[str, Any]] = []

        # Запрос #1 — обязательные данные (min)
        q_min = queries[0] if queries else f"{participant} {discipline}"
        if match_date:
            q_min = f"{q_min} {match_date}"
        res_min = await _search_primary(q_min, f"{participant} min")
        participant_results.extend(res_min)

        # Запрос #2 — расширенные данные (max)
        if len(queries) >= 2:
            q_max = queries[1]
            if match_date:
                q_max = f"{q_max} {match_date}"
            res_max = await _search_primary(q_max, f"{participant} max")
            participant_results.extend(res_max)

        all_results[participant] = participant_results

    # H2H запрос
    if len(participants) >= 2:
        h2h_q = get_h2h_query(config, participants[0], participants[1], discipline, is_russian)
        h2h_results = await _search_primary(h2h_q, "H2H")
        all_results["h2h"] = h2h_results

    # Обогащение: скачиваем выжимки со страниц (до 3 лучших на участника)
    fetch_tasks = []
    fetch_meta = []  # (key, idx) для привязки результатов
    for key, results in all_results.items():
        for i, r in enumerate(results[:3]):
            url = r.get("href", "")
            entity = key if key != "h2h" else f"{participants[0]} {participants[1]}"
            fetch_tasks.append(_fetch_page_excerpt_async(url, entity))
            fetch_meta.append((key, i))

    if fetch_tasks:
        excerpts = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        for (key, idx), excerpt in zip(fetch_meta, excerpts):
            if isinstance(excerpt, str) and excerpt:
                all_results[key][idx]["excerpt"] = excerpt

    # ── Проверка required_data и расширенный поиск при нехватке ──
    for participant in participants:
        results = all_results.get(participant, [])
        # Собираем весь текст для проверки (snippets + excerpts + pre_validated)
        text_parts = []
        for r in results:
            text_parts.append(r.get("title", ""))
            text_parts.append(r.get("body", ""))
            text_parts.append(r.get("excerpt", ""))
        # Добавляем pre_validated данные
        for src in pre_validated:
            text_parts.append(src.get("title", ""))
            text_parts.append(src.get("body", ""))
            text_parts.append(src.get("excerpt", ""))
        collected_text = " ".join(text_parts)

        check = check_required_data(collected_text, required_keys, discipline)
        if check["missing"]:
            logger.info("[COLLECT] %s: missing required_data: %s → расширенный поиск",
                        participant, check["missing"])
            extended = await _search_extended(participant, check["missing"])
            if extended:
                all_results[participant].extend(extended)
                # Обогащаем выжимками новые результаты
                ext_tasks = []
                ext_meta = []
                base_idx = len(results)
                for j, r in enumerate(extended[:2]):
                    url = r.get("href", "")
                    ext_tasks.append(_fetch_page_excerpt_async(url, participant))
                    ext_meta.append((participant, base_idx + j))
                if ext_tasks:
                    ext_excerpts = await asyncio.gather(*ext_tasks, return_exceptions=True)
                    for (k, idx), exc in zip(ext_meta, ext_excerpts):
                        if isinstance(exc, str) and exc:
                            all_results[k][idx]["excerpt"] = exc

    # Форматируем отчёт
    parts = []
    for participant in participants:
        results = all_results.get(participant, [])
        if not results:
            parts.append(f"\n--- {participant.upper()} ---\nДанные не найдены.")
            continue
        lines = [f"\n--- {participant.upper()} ---"]
        for r in results:
            lines.append(f"Источник: {_extract_source(r.get('href', ''))} ({r.get('search_engine', '')})")
            lines.append(f"Заголовок: {r.get('title', '')}")
            lines.append(f"Сниппет: {r.get('body', '')[:400]}")
            excerpt = r.get("excerpt", "")
            if excerpt:
                lines.append(f"Выжимка: {excerpt[:800]}")
            lines.append(f"Ссылка: {r.get('href', '')}")
            lines.append("")
        parts.append("\n".join(lines))

    h2h_results = all_results.get("h2h", [])
    if h2h_results:
        lines = ["\n--- H2H ---"]
        for r in h2h_results:
            lines.append(f"Источник: {_extract_source(r.get('href', ''))} ({r.get('search_engine', '')})")
            lines.append(f"Заголовок: {r.get('title', '')}")
            lines.append(f"Сниппет: {r.get('body', '')[:400]}")
            excerpt = r.get("excerpt", "")
            if excerpt:
                lines.append(f"Выжимка: {excerpt[:800]}")
            lines.append(f"Ссылка: {r.get('href', '')}")
            lines.append("")
        parts.append("\n".join(lines))

    total_sources = sum(len(v) for v in all_results.values())
    header = f"Дисциплина: {discipline} | Источников: {total_sources} | Язык запросов: {'RU' if is_russian else 'EN'}"
    return header + "\n" + "\n".join(parts)


