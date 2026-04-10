"""Вспомогательные функции: нормализация, валидация, определение региона, выбор сайтов."""

import logging
import re
from typing import List, Optional
from urllib.parse import urlparse

from services.name_normalizer import (
    expand_context_terms,
    get_search_variants,
    normalize_entity_name,
    transliterate_text,
)
from services.search_providers.config import (
    DISCIPLINE_SOURCE_CONFIG,
    DISCIPLINE_SITES,
    DISCIPLINE_VALIDATION_ALIASES,
    RUSSIAN_CONTEXT_HINTS,
    RUSSIAN_PARTICIPANT_HINTS,
    SEARCH_MAX_SITES,
)

logger = logging.getLogger(__name__)


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


def _is_result_valid(entity: str, title: str, body: str, excerpt: str, url: str = "") -> bool:
    url_text = urlparse(url).path.replace("-", " ").replace("_", " ") if url else ""
    haystack = f"{title} {body} {excerpt} {url_text}".lower()
    entity_tokens = _normalize_tokens(entity)
    if not entity_tokens:
        return False
    matched = sum(1 for token in entity_tokens if token in haystack)
    if len(entity_tokens) == 1:
        return matched >= 1
    return matched >= min(2, len(entity_tokens))
