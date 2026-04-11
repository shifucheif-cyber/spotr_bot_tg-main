"""In-memory TTL cache for LLM analysis results.

Prevents duplicate LLM calls when multiple users request the same match.
Pattern mirrors data_fetcher._match_cache.
Supports phase-based TTL via services.event_phase.
"""

import hashlib
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from services.event_phase import EventPhase, get_phase_ttl

logger = logging.getLogger(__name__)

_analysis_cache: Dict[str, Dict[str, Any]] = {}
_DEFAULT_LLM_TTL = timedelta(hours=2)
_CACHE_MAX = 100
_cache_lock = threading.Lock()


def analysis_cache_key(discipline: str, match_name: str, date: str = "") -> str:
    """Deterministic, order-independent cache key."""
    parts = match_name.lower().replace(" vs ", "|").replace(" против ", "|").split("|")
    parts = sorted(p.strip() for p in parts if p.strip())
    raw = f"{discipline.lower()}:{'|'.join(parts)}:{date.strip().lower()}"
    return hashlib.md5(raw.encode()).hexdigest()


def get_cached_analysis(key: str, phase: EventPhase | None = None) -> Optional[Dict[str, Any]]:
    """Return cached {provider, text} or None if missing/expired.

    TTL is determined by event phase when provided, otherwise defaults to 2h.
    """
    ttl = get_phase_ttl(phase) if phase is not None else _DEFAULT_LLM_TTL
    with _cache_lock:
        entry = _analysis_cache.get(key)
        if entry is None:
            return None
        if datetime.now(tz=timezone.utc) - entry["ts"] > ttl:
            del _analysis_cache[key]
            return None
        return entry["result"]


def put_cached_analysis(key: str, result: Dict[str, Any]) -> None:
    """Store analysis result with current timestamp. Evicts oldest if full."""
    with _cache_lock:
        if len(_analysis_cache) >= _CACHE_MAX:
            oldest = min(_analysis_cache, key=lambda k: _analysis_cache[k]["ts"])
            del _analysis_cache[oldest]
        _analysis_cache[key] = {"result": result, "ts": datetime.now(tz=timezone.utc)}


def cleanup_expired_cache() -> int:
    """Remove entries older than 48h (max possible TTL). Returns count removed."""
    max_ttl = timedelta(hours=48)
    with _cache_lock:
        now = datetime.now(tz=timezone.utc)
        expired = [k for k, v in _analysis_cache.items() if now - v["ts"] > max_ttl]
        for k in expired:
            del _analysis_cache[k]
        if expired:
            logger.info("Analysis cache cleanup: removed %d, %d remaining", len(expired), len(_analysis_cache))
        return len(expired)
