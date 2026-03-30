import argparse
import asyncio
import json
import sys
from typing import Any, Dict, Optional

from data_router import get_match_data
from services.name_normalizer import resolve_match_entities, split_match_text


def build_experiment_prompt(bundle: Dict[str, Any]) -> str:
    return (
        "Ты работаешь в тестовом двухэтапном режиме. Сначала опирайся только на факты ниже, "
        "не выдумывай отсутствующие данные. Затем сделай короткий прогноз и явно отдели "
        "подтвержденные факты от предположений.\n\n"
        f"Дисциплина: {bundle['discipline']}\n"
        f"Матч: {bundle['corrected_match']}\n"
        f"Дата: {bundle['match_context'].get('date', '')}\n"
        f"Лига: {bundle['match_context'].get('league', '')}\n\n"
        "Этап 1. Подтвержденные факты и источники:\n"
        f"{bundle['facts']}\n\n"
        "Этап 2. Требования к ответу:\n"
        "1. Коротко перечисли, какие факты действительно удалось найти.\n"
        "2. Укажи, каких данных не хватает.\n"
        "3. Дай осторожный прогноз по критериям дисциплины.\n"
        "4. Не выдавай догадки за факты."
    )


async def collect_fact_bundle(match_text: str, discipline: str, date_text: str, league: str = "") -> Dict[str, Any]:
    sides = split_match_text(match_text)
    if len(sides) != 2:
        raise ValueError("Матч должен быть в формате 'Команда 1 vs Команда 2'")

    resolved = resolve_match_entities(sides[0], sides[1], discipline=discipline)
    match_context = {
        "date": date_text,
        "league": league,
        "sport": "experiment",
        "home": resolved["team1"]["corrected"],
        "away": resolved["team2"]["corrected"],
    }
    facts = await get_match_data(resolved["match"], discipline, match_context=match_context)
    return {
        "discipline": discipline,
        "original_match": match_text,
        "corrected_match": resolved["match"],
        "corrections": resolved,
        "match_context": match_context,
        "facts": facts,
        "prompt": build_experiment_prompt(
            {
                "discipline": discipline,
                "corrected_match": resolved["match"],
                "match_context": match_context,
                "facts": facts,
            }
        ),
    }


async def run_experiment(match_text: str, discipline: str, date_text: str, league: str = "", use_llm: bool = False) -> Dict[str, Any]:
    bundle = await collect_fact_bundle(match_text, discipline, date_text, league=league)
    result = {"bundle": bundle}

    if use_llm:
        from bot import generate_content

        try:
            result["analysis"] = await generate_content(bundle["prompt"], discipline=discipline, discipline_key=None)
        except Exception as exc:
            result["analysis"] = ""
            result["analysis_error"] = str(exc)

    return result


async def _main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Standalone two-stage fact collection and analysis experiment")
    parser.add_argument("--match", required=True, help="Match in format 'Team A vs Team B'")
    parser.add_argument("--discipline", required=True, help="Discipline name")
    parser.add_argument("--date", required=True, help="Match date")
    parser.add_argument("--league", default="", help="League or tournament")
    parser.add_argument("--use-llm", action="store_true", help="Run LLM analysis after fact collection")
    args = parser.parse_args()

    result = await run_experiment(
        match_text=args.match,
        discipline=args.discipline,
        date_text=args.date,
        league=args.league,
        use_llm=args.use_llm,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())