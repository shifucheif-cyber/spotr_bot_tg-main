import os
import re
import json
from typing import Optional


QUIET_E2E_SUMMARY = os.getenv("QUIET_E2E_SUMMARY", "false").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_prediction(text: str) -> str:
    if not text:
        return "unknown"

    patterns = [
        r"🏆\s*\*\*Исход:\*\*\s*(.+)",
        r"Прогноз победителя:\s*(.+)",
        r"Тотал карт:\s*(.+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()

    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:140]
    return "unknown"


def _extract_analysis_engines(search_text: str) -> str:
    if not search_text:
        return "none"

    engines = set()

    match = re.search(r"Аналитический поиск \(Exa/Tavily\):\s*(.+)", search_text)
    if match:
        raw = match.group(1).strip()
        if raw and raw.lower() != "нет":
            for item in raw.split(","):
                cleaned = item.strip().lower()
                if cleaned:
                    engines.add(cleaned)

    for engine in ("exa", "tavily"):
        if re.search(rf"\b{engine}\b", search_text, flags=re.IGNORECASE):
            engines.add(engine)

    return ",".join(sorted(engines)) if engines else "none"


def _discipline_status(requested: str, actual: str, clarification_type: Optional[str]) -> str:
    if clarification_type == "discipline_mismatch":
        return f"mismatch:{actual or 'unknown'}"
    if actual:
        return f"confirmed:{actual}"
    if requested:
        return f"requested:{requested}"
    return "unknown"


def emit_quiet_e2e_summary(
    *,
    match_text: str,
    requested_discipline: str,
    actual_discipline: str,
    clarification_type: Optional[str],
    search_text: str,
    llm_provider: str,
    final_text: str,
) -> None:
    if not QUIET_E2E_SUMMARY:
        return

    match_status = "confirmed" if match_text else "unknown"
    discipline_status = _discipline_status(requested_discipline, actual_discipline, clarification_type)
    analysis_engines = _extract_analysis_engines(search_text)
    prediction = _normalize_prediction(final_text)

    summary = {
        "match": {
            "status": match_status,
            "name": match_text or "unknown",
        },
        "discipline": discipline_status,
        "analysis_engines": analysis_engines,
        "llm_provider": llm_provider or "unknown",
        "result": prediction,
    }
    print("E2E_SUMMARY=" + json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
