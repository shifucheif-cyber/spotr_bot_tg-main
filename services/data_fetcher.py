"""
Universal data fetching module for match analysis.
Handles verification from multiple sources and data extraction.
"""

import asyncio
import hashlib
import logging
import re
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone

from services.search_engine import (
    collect_discipline_data,
    check_required_data,
)
from services.event_phase import EventPhase, get_event_phase, get_phase_ttl, is_event_expired

logger = logging.getLogger(__name__)

# ── Match analysis cache ──
# Key: hash(discipline, sorted participants) → {"result": str, "ts": datetime}
_match_cache: Dict[str, Dict[str, Any]] = {}
_DEFAULT_SEARCH_TTL = timedelta(hours=24)
_CACHE_MAX = 200
_cache_lock = asyncio.Lock()


def _cache_key(discipline: str, side1: str, side2: str, match_date: str = "") -> str:
    """Детерминированный ключ: дисциплина + отсортированные участники + дата."""
    parts = sorted([side1.strip().lower(), side2.strip().lower()])
    raw = f"{discipline.strip().lower()}|{parts[0]}|{parts[1]}|{match_date.strip().lower()}"
    return hashlib.md5(raw.encode()).hexdigest()


async def _get_cached(key: str, phase: EventPhase | None = None) -> Optional[str]:
    ttl = get_phase_ttl(phase) if phase is not None else _DEFAULT_SEARCH_TTL
    async with _cache_lock:
        entry = _match_cache.get(key)
        if not entry:
            return None
        if datetime.now(tz=timezone.utc) - entry["ts"] > ttl:
            del _match_cache[key]
            return None
        logger.info("Cache hit for match analysis (key=%s)", key[:8])
        return entry["result"]


async def _put_cache(key: str, result: str) -> None:
    async with _cache_lock:
        if len(_match_cache) >= _CACHE_MAX:
            # удаляем самый старый
            oldest = min(_match_cache, key=lambda k: _match_cache[k]["ts"])
            del _match_cache[oldest]
        _match_cache[key] = {"result": result, "ts": datetime.now(tz=timezone.utc)}


# ── Discipline marker classes ──
# Used by *_service.py as discipline identifiers passed to fetch_match_analysis_data.
# The actual data fetching is done by collect_discipline_data() from search_engine.

class CS2Fetcher:
    _discipline = "cs2"

class EsportsGameFetcher:
    def __init__(self, game_key: str):
        self.game_key = game_key
        self._discipline = game_key

class FootballFetcher:
    _discipline = "football"

class TennisFetcher:
    _discipline = "tennis"

class MMAFetcher:
    def __init__(self, subdiscipline: str = "mma"):
        self._discipline = "boxing" if subdiscipline == "boxing" else "mma"

class BasketballFetcher:
    _discipline = "basketball"

class HockeyFetcher:
    _discipline = "hockey"

class TableTennisFetcher:
    _discipline = "table_tennis"

class VolleyballFetcher:
    _discipline = "volleyball"


async def fetch_match_analysis_data(
    match_name: str,
    fetcher,
    fetch_method: str = "",
    emoji: str = "⚡",
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

    # ── Проверяем фазу события и кэш ──
    discipline = getattr(fetcher, '_discipline', None) or getattr(fetcher, 'game_key', None) or fetcher.__class__.__name__.replace('Fetcher', '').lower()
    match_date = (match_context or {}).get("date", "")
    phase = get_event_phase(match_date, discipline)
    cache_k = _cache_key(discipline, side1, side2, match_date)

    # Block expired events
    if is_event_expired(phase):
        return "⛔ Событие завершено более 24ч назад. Анализ неактуален."

    # Finished events — serve cache ≤48h or message
    if phase is EventPhase.FINISHED:
        cached = await _get_cached(cache_k, phase=phase)
        if cached is not None:
            logger.info("[FETCH] Event FINISHED, returning cached data (≤48h)")
            return cached
        return "⚠️ Событие завершено. Данные устарели, уточните запрос."

    cached = await _get_cached(cache_k, phase=phase)
    if cached is not None:
        logger.info(f"[FETCH] Найден кэш для ключа: {cache_k}")
        return cached

    # ── Новый пайплайн: collect_discipline_data (Serper→Tavily/Exa→DDG) ──
    try:
        logger.info(f"[FETCH] collect_discipline_data для [{side1}, {side2}], discipline={discipline}")
        report = await collect_discipline_data(
            [side1, side2],
            discipline,
            match_context=match_context,
        )
    except Exception as e:
        logger.error("[FETCH] collect_discipline_data failed: %s", e)
        report = ""

    parts = [f"{emoji} Матч: {side1.upper()} vs {side2.upper()}"]
    if report:
        # Min-data gate: проверяем наличие обязательных данных
        from services.discipline_config import get_config as _get_config
        _cfg = _get_config(discipline)
        req_keys = _cfg.get("required_data", []) if _cfg else []
        if req_keys:
            data_check = check_required_data(report, req_keys, discipline)
            if data_check["missing"]:
                missing_str = ", ".join(data_check["missing"])
                report += f"\n\n⚠️ Не найдены обязательные данные: {missing_str}. Анализ может быть неточным."
                logger.warning("[FETCH] Missing required_data for %s: %s", discipline, data_check["missing"])
        parts.append(report)
    else:
        parts.append("\nДанные из поисковых источников не найдены. Анализируйте на основе общих знаний.")

    result = "\n".join(parts)
    await _put_cache(cache_k, result)
    return result


async def cleanup_expired_cache() -> int:
    """Удаляет записи старше 48ч (макс. возможный TTL). Возвращает количество удалённых."""
    max_ttl = timedelta(hours=48)
    async with _cache_lock:
        now = datetime.now(tz=timezone.utc)
        expired = [k for k, v in _match_cache.items() if now - v["ts"] > max_ttl]
        for k in expired:
            del _match_cache[k]
        if expired:
            logger.info("Data cache cleanup: removed %d expired entries, %d remaining", len(expired), len(_match_cache))
        return len(expired)
