"""Search and validation helpers for multi-source sports data collection.

Пайплайн данных:
1) validate_match_request() — DDG-валидация сущности/события.
2) collect_discipline_data() — сбор данных для анализа:
   Serper → Tavily/Exa → DDG (последний резерв).
   По 2 запроса на участника + 1 H2H.
3) collect_validated_sources() — legacy-каскад (DDG→Serper→Exa/Tavily),
   используется в validate_match_request.

Провайдеры и конфиг вынесены в services/search_providers/.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from services.name_normalizer import split_match_text

# --- Re-exports from search_providers (сохраняем обратную совместимость) ---
from services.search_providers.config import (
    DISCIPLINE_SOURCE_CONFIG,
    DISCIPLINE_SITES,
    DISCIPLINE_VALIDATION_ALIASES,
    EXA_API_KEY,
    GOOGLE_BACKOFF_SECONDS,
    REQUEST_HEADERS,
    REQUEST_TIMEOUT,
    RUSSIAN_CONTEXT_HINTS,
    RUSSIAN_PARTICIPANT_HINTS,
    SEARCH_ANALYSIS_MAX_SNIPPETS,
    SEARCH_ANALYSIS_PROVIDER,
    SEARCH_ANALYSIS_RESULTS_PER_QUERY,
    SEARCH_MAX_SITES,
    SEARCH_SERP_SUPPLEMENT_TERMS,
    SERPER_API_KEY,
    TAVILY_API_KEY,
    _DISCIPLINE_SEARCH_LABEL,
    _REQUIRED_DATA_PATTERNS,
    _google_backoff_until,
)
from services.search_providers.helpers import (
    _build_site_queries,
    _clean_context_terms,
    _extract_source,
    _get_sites_for_query,
    _is_result_valid,
    _looks_like_russian_context,
    _looks_like_russian_participant,
    _matches_russian_hint,
    _normalize_tokens,
    _normalize_validation_discipline_key,
    _should_prefer_russian_sources,
)
from services.search_providers.providers import (
    DDGS,
    _analysis_providers,
    _fetch_page_excerpt,
    _fetch_page_excerpt_async,
    _get_sync_executor,
    _merge_analysis_results,
    _search_with_exa,
    _search_with_tavily,
    search_with_ddgs,
    search_with_serper,
)

logger = logging.getLogger(__name__)


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

    extra_queries = []
    if entity and context_terms:
        h2h_query = f"{context_terms} last 5 matches scores and head-to-head"
        extra_queries.append(h2h_query)
    if entity:
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


async def collect_validated_sources(
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

    async def _main_async():
        nonlocal all_sites, trusted_domains, fallback_attempted
        if DDGS is not None:
            ddg_query = f"{entity} {discipline_label} {stat_type}{context_suffix}"
            logger.info("[VALIDATE] DDG phase: %s", ddg_query)
            ddg_results = await search_with_ddgs(
                ddg_query, num_results=max(6, min_sources + 4), timelimit=timelimit
            )
            _validate_and_collect(ddg_results)
            logger.info("[VALIDATE] After DDG: %d validated for '%s'", len(validated_sources), entity)

        if len(validated_sources) >= min_sources:
            logger.info("[VALIDATE] After DDG достаточно данных: %d", len(validated_sources))
            return _enough_payload()

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

        if (EXA_API_KEY or TAVILY_API_KEY):
            logger.info(f"[VALIDATE] Exa/Tavily phase: entity={entity}, discipline={discipline}, stat_type={stat_type}, context_terms={context_terms}")
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

    return await _main_async()


async def validate_match_request(match_text: str, date_text: str, discipline: str) -> Dict[str, Any]:
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
        ev_hits = await search_with_ddgs(match_q, num_results=5, timelimit="m")
        if ev_hits:
            event_note = f"Событие (DDG): найдено {len(ev_hits)} ссылок по запросу матча.\n\n"
        else:
            event_note = (
                "Событие (DDG): по полному запросу мало ссылок — дальше валидация участников (DDG → Serper).\n\n"
            )

    participant_reports = []
    regions = []
    for side in sides:
        rep = await collect_validated_sources(
            side,
            discipline_key,
            "official team player roster ranking profile recent results current season",
            min_sources=1,
            timelimit="m",
            context_terms=None,
        )
        participant_reports.append(rep)
        region = None
        for src in rep.get("validated_sources", []):
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

def check_required_data(
    collected_text: str,
    required_keys: List[str],
    discipline: str = "",
) -> Dict[str, Any]:
    """Проверяет наличие обязательных данных в собранном тексте."""
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
    """
    from services.discipline_config import get_config, get_search_queries, get_h2h_query

    config = get_config(discipline)
    if not config:
        logger.warning("[COLLECT] Нет конфига для дисциплины: %s", discipline)
        return f"Дисциплина '{discipline}' не поддерживается."

    context_str = " ".join(participants) + " " + (match_context or {}).get("league", "")
    is_russian = _should_prefer_russian_sources(participants[0], context_str, discipline)

    all_results: Dict[str, List[Dict[str, Any]]] = {}
    seen_urls: set = set()

    pre_validated = (match_context or {}).get("pre_validated_sources", [])
    if pre_validated:
        for src in pre_validated:
            url = src.get("href", "")
            if url:
                seen_urls.add(url)

    async def _search_primary(query: str, label: str, num: int = 5) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
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
        if DDGS is not None:
            ddg_res = await search_with_ddgs(query, num_results=num, timelimit="m")
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
        if not (TAVILY_API_KEY or EXA_API_KEY):
            return []

        results: List[Dict[str, Any]] = []
        sites = [e["site"] for e in DISCIPLINE_SOURCE_CONFIG.get(discipline, [])]

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

    match_date = (match_context or {}).get("date", "")
    required_keys = config.get("required_data", [])

    for participant in participants:
        queries = get_search_queries(config, participant, discipline, is_russian)
        participant_results: List[Dict[str, Any]] = []

        q_min = queries[0] if queries else f"{participant} {discipline}"
        if match_date:
            q_min = f"{q_min} {match_date}"
        res_min = await _search_primary(q_min, f"{participant} min")
        participant_results.extend(res_min)

        if len(queries) >= 2:
            q_max = queries[1]
            if match_date:
                q_max = f"{q_max} {match_date}"
            res_max = await _search_primary(q_max, f"{participant} max")
            participant_results.extend(res_max)

        all_results[participant] = participant_results

    if len(participants) >= 2:
        h2h_q = get_h2h_query(config, participants[0], participants[1], discipline, is_russian)
        h2h_results = await _search_primary(h2h_q, "H2H")
        all_results["h2h"] = h2h_results

    fetch_tasks = []
    fetch_meta = []
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

    for participant in participants:
        results = all_results.get(participant, [])
        text_parts = []
        for r in results:
            text_parts.append(r.get("title", ""))
            text_parts.append(r.get("body", ""))
            text_parts.append(r.get("excerpt", ""))
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
