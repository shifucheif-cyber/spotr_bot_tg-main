import argparse
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from dotenv import load_dotenv
import requests

from data_router import get_match_data
from services.e2e_summary import emit_quiet_e2e_summary
from services.logging_utils import configure_console_output, configure_logging
from services.name_normalizer import resolve_match_entities, split_match_text
from services.search_engine import DISCIPLINE_SOURCE_CONFIG

load_dotenv()

configure_console_output()
configure_logging(default_level="WARNING")
logger = logging.getLogger(__name__)

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()
LLM_FALLBACK_ORDER = ["groq", "deepseek", "google"]

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-1.5")
GOOGLE_API_VERSION = os.getenv("GOOGLE_API_VERSION", "v1")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
EXA_API_KEY = os.getenv("EXA_API_KEY")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "compound-beta-mini")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL")
GROQ_STABLE_MODELS = [
    "llama-3.3-70b-versatile",
    "mixtral-8x7b-32768",
    "llama-3.1-8b-instant",
    "llama3-70b-8192",
    "llama3-8b-8192",
]

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

PROJECT_DATA_TIMEOUT = max(5, int(os.getenv("EXPERIMENT_PROJECT_DATA_TIMEOUT", "25")))
SEARCH_STAGE_TIMEOUT = max(10, int(os.getenv("EXPERIMENT_LLM_SEARCH_TIMEOUT", "45")))
ANALYSIS_STAGE_TIMEOUT = max(10, int(os.getenv("EXPERIMENT_LLM_ANALYSIS_TIMEOUT", "45")))
EXPERIMENT_TAVILY_ONLY = os.getenv("EXPERIMENT_TAVILY_ONLY", "true").strip().lower() in {"1", "true", "yes", "on"}
EXPERIMENT_SEARCH_PROVIDER = os.getenv("EXPERIMENT_SEARCH_PROVIDER", "tavily").strip().lower()

SEARCH_STAGE_SYSTEM_PROMPT = """Ты работаешь в изолированном экспериментальном режиме.
Твоя роль: LLM-поиск по уже собранным данным проекта.

Правила:
1. Используй только данные из блока PROJECT_DATA.
2. Ничего не придумывай и не дополняй внешними знаниями.
3. Верни только JSON без markdown и без пояснений.
4. Если данных мало, честно укажи это в полях missing_data и data_quality.
5. В confirmed_facts включай только факты, которые можно прямо опереть на PROJECT_DATA.

Верни JSON строго такого вида:
{
  "match": "...",
  "discipline": "...",
  "data_quality": "enough|limited|poor",
  "confirmed_facts": [
    {
      "topic": "...",
      "fact": "...",
      "evidence": "...",
      "source_hint": "..."
    }
  ],
  "missing_data": ["..."],
  "risk_flags": ["..."],
  "search_summary": "..."
}
"""

ANALYSIS_STAGE_SYSTEM_PROMPT = """Ты работаешь в изолированном экспериментальном режиме.
Твоя роль: аналитик, который получает только структурированные факты после LLM-поиска.

Правила:
1. Используй только JSON из SEARCH_RESULT.
2. Явно отделяй подтвержденные факты от предположений.
3. Если данных мало, снижай уверенность и прямо об этом пиши.
4. Не подменяй отсутствие данных выдумкой.
5. Даже при неполных данных ты обязан дать конкретный прогноз по победителю и тоталу карт.
6. Если фактов мало, выбери наиболее вероятный сценарий и прямо пометь, что это low-confidence lean, а не сильный value pick.

Формат ответа:
1. Подтвержденные факты
2. Чего не хватает
3. Ключевые факторы матча
4. Прогноз победителя: <название команды>
5. Тотал карт: <Меньше 2.5 / Больше 2.5 / 2 карты / 3 карты>
6. Короткое объяснение прогноза
7. Уровень уверенности: низкий/средний/высокий
"""


DISCIPLINE_ALIASES = {
    "cs2": "cs2",
    "cs 2": "cs2",
    "cs:2": "cs2",
    "cs": "cs2",
    "counter strike 2": "cs2",
    "counter-strike 2": "cs2",
    "counter strike": "cs2",
    "counter-strike": "cs2",
    "dota 2": "dota2",
    "dota2": "dota2",
    "league of legends": "lol",
    "lol": "lol",
    "valorant": "valorant",
    "football": "football",
    "soccer": "football",
    "футбол": "football",
    "hockey": "hockey",
    "хоккей": "hockey",
    "basketball": "basketball",
    "баскетбол": "basketball",
    "volleyball": "volleyball",
    "волейбол": "volleyball",
    "tennis": "tennis",
    "теннис": "tennis",
    "table tennis": "table_tennis",
    "table_tennis": "table_tennis",
    "настольный теннис": "table_tennis",
    "mma": "mma",
    "мма": "mma",
    "boxing": "boxing",
    "бокс": "boxing",
}


def build_annotation_block(match_text: str) -> str:
    sides = split_match_text(match_text)
    if len(sides) != 2:
        return ""
    return "Данные матча:\n1️⃣ {}\n2️⃣ {}".format(sides[0], sides[1])


def normalize_discipline_label(discipline: str) -> str:
    cleaned = re.sub(r"\s+", " ", discipline.strip().lower())
    return DISCIPLINE_ALIASES.get(cleaned, cleaned)


def _parse_match_datetime(date_text: str) -> list[str]:
    candidates = []
    formats = ["%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d"]
    for fmt in formats:
        try:
            parsed = datetime.strptime(date_text.strip(), fmt)
            candidates.extend([
                parsed.strftime("%Y-%m-%d"),
                parsed.strftime("%d.%m.%Y"),
                parsed.strftime("%d %B %Y"),
            ])
            break
        except ValueError:
            continue
    deduplicated = []
    seen = set()
    for item in candidates:
        normalized = item.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduplicated.append(item)
    return deduplicated


def _build_deep_queries(team1: str, team2: str, discipline: str, date_text: str) -> list[str]:
    sites = [entry["site"] for entry in DISCIPLINE_SOURCE_CONFIG.get(discipline, [])[:4]]
    date_variants = _parse_match_datetime(date_text)
    query_templates = [
        f'"{team1}" "{team2}"',
        f'{team1} {team2}',
        f'{team1} vs {team2}',
    ]
    if discipline == "cs2":
        query_templates.extend([
            f'{team1} {team2} cs2',
            f'{team1} {team2} hltv',
            f'{team1} {team2} liquipedia',
            f'{team1} {team2} counter strike 2',
        ])

    queries: list[str] = []
    for site in sites:
        for query in query_templates:
            queries.append(f"{query} site:{site}")
            for date_variant in date_variants[:2]:
                queries.append(f"{query} {date_variant} site:{site}")

    deduplicated = []
    seen = set()
    for query in queries:
        normalized = query.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduplicated.append(query)
    return deduplicated[:16]


def _get_search_domains(discipline: str) -> list[str]:
    return [entry["site"] for entry in DISCIPLINE_SOURCE_CONFIG.get(discipline, [])[:4]]


def search_with_exa(query: str, discipline: str, max_results: int = 5) -> dict[str, Any]:
    if not EXA_API_KEY:
        return {"answer": "", "results": []}

    payload: Dict[str, Any] = {
        "query": query,
        "numResults": max_results,
        "contents": {
            "text": {
                "maxCharacters": 1200,
            }
        },
    }
    include_domains = _get_search_domains(discipline)
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
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.warning("Exa search failed for query '%s': %s", query, exc)
        return {"answer": "", "results": []}

    results = []
    for item in data.get("results", []):
        text = (item.get("text") or "").strip()
        highlights = item.get("highlights") or []
        if not text and isinstance(highlights, list):
            text = " ".join(str(highlight).strip() for highlight in highlights if highlight).strip()
        results.append(
            {
                "title": (item.get("title") or "").strip(),
                "body": text,
                "href": (item.get("url") or "").strip(),
                "search_engine": "exa",
            }
        )

    logger.info("Found %s Exa results for query: %s", len(results), query)
    return {"answer": "", "results": results}


def search_with_tavily(query: str, discipline: str, max_results: int = 5) -> dict[str, Any]:
    if not TAVILY_API_KEY:
        return {"answer": "", "results": []}

    try:
        from tavily import TavilyClient
    except ImportError:
        logger.warning("tavily-python is not installed; skipping Tavily search")
        return {"answer": "", "results": []}

    include_domains = _get_search_domains(discipline)
    client = TavilyClient(api_key=TAVILY_API_KEY)
    try:
        response = client.search(
            query=query,
            topic="general",
            search_depth="advanced",
            max_results=max_results,
            include_domains=include_domains or None,
            include_answer=True,
            include_raw_content=False,
        )
    except Exception as exc:
        logger.warning("Tavily search failed for query '%s': %s", query, exc)
        return {"answer": "", "results": []}

    results = []
    for item in response.get("results", []):
        results.append(
            {
                "title": (item.get("title") or "").strip(),
                "body": (item.get("content") or item.get("snippet") or "").strip(),
                "href": (item.get("url") or "").strip(),
                "search_engine": "tavily",
            }
        )

    logger.info("Found %s Tavily results for query: %s", len(results), query)
    answer = response.get("answer") or ""
    return {"answer": answer.strip(), "results": results}


def _search_query_with_provider(query: str, discipline: str) -> list[dict[str, Any]]:
    provider = EXPERIMENT_SEARCH_PROVIDER
    if provider == "exa":
        return [{"provider": "exa", "payload": search_with_exa(query, discipline, max_results=3)}]
    if provider == "hybrid":
        return [
            {"provider": "exa", "payload": search_with_exa(query, discipline, max_results=3)},
            {"provider": "tavily", "payload": search_with_tavily(query, discipline, max_results=3)},
        ]
    return [{"provider": "tavily", "payload": search_with_tavily(query, discipline, max_results=3)}]


def collect_deep_project_search(match_text: str, discipline: str, date_text: str) -> str:
    teams = split_match_text(match_text)
    if len(teams) != 2:
        return ""

    snippets = []
    seen_urls = set()
    provider_answers = []
    seen_answers = set()
    for query in _build_deep_queries(teams[0], teams[1], discipline, date_text):
        for search_payload in _search_query_with_provider(query, discipline):
            provider_name = search_payload["provider"]
            payload = search_payload["payload"]
            answer = (payload.get("answer") or "").strip()
            if answer:
                normalized_answer = answer.lower()
                if normalized_answer not in seen_answers:
                    seen_answers.add(normalized_answer)
                    provider_answers.append(
                        "\n".join(
                            [
                                f"Query: {query}",
                                f"{provider_name.title()} answer: {answer}",
                            ]
                        )
                    )
            results = payload.get("results") or []
            for result in results:
                href = result.get("href", "")
                if not href or href in seen_urls:
                    continue
                seen_urls.add(href)
                title = result.get("title", "").strip()
                body = result.get("body", "").strip()
                engine = result.get("search_engine", provider_name)
                snippets.append(
                    "\n".join(
                        [
                            f"Query: {query}",
                            f"Engine: {engine}",
                            f"Title: {title or 'n/a'}",
                            f"Snippet: {body or 'n/a'}",
                            f"URL: {href}",
                        ]
                    )
                )
                if len(snippets) >= 8:
                    break
            if len(snippets) >= 8:
                break
        if len(snippets) >= 8:
            break

    sections = []
    if provider_answers:
        sections.append("SEARCH_PROVIDER_ANSWERS:\n" + "\n\n".join(provider_answers[:4]))
    if snippets:
        sections.append("DEEP_PROJECT_SEARCH:\n" + "\n\n".join(snippets))

    if not sections:
        return ""

    return "\n\n" + "\n\n".join(sections)


def build_tavily_only_project_data(match_text: str, discipline: str, date_text: str, league: str = "") -> str:
    teams = split_match_text(match_text)
    sections = [f"Матч: {match_text}"]

    if league:
        sections.append(f"Лига/турнир: {league}")
    if date_text:
        sections.append(f"Дата: {date_text}")

    if len(teams) == 2:
        sections.append(
            "Фокус анализа:\n"
            f"- Команда 1: {teams[0]}\n"
            f"- Команда 2: {teams[1]}\n"
            "- Последние матчи и форма\n"
            "- Составы и возможные замены\n"
            "- Пул карт и предпочтения\n"
            "- Очные встречи\n"
            "- Текущий рейтинг и общий уровень"
        )

    deep_search_notes = collect_deep_project_search(match_text, discipline, date_text)
    if deep_search_notes:
        sections.append(deep_search_notes)

    return "\n\n".join(section for section in sections if section)


def choose_google_model(client: Any, default_model: str) -> str:
    try:
        available = [model.name for model in client.models.list(config={"page_size": 50})]
    except Exception as exc:
        logger.warning("Unable to list Google models, using default %s: %s", default_model, exc)
        return default_model

    if not available:
        return default_model

    for model in available:
        if model == default_model or model.endswith(f"/{default_model}"):
            return model

    preferred = [
        default_model,
        "gemini-2.0-flash-lite-001",
        "gemini-2.0-flash-lite",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash-001",
        "gemini-2.0-flash",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
    ]
    for candidate in preferred:
        for model in available:
            if model == candidate or model.endswith(f"/{candidate}") or candidate in model:
                return model
    return available[0]


def _extract_json_object(text: str) -> Dict[str, Any]:
    raw = text.strip()
    fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, flags=re.S)
    if fenced_match:
        raw = fenced_match.group(1).strip()
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start:end + 1]
    return json.loads(raw)


def _resolve_groq_base_url() -> Optional[str]:
    if not GROQ_BASE_URL:
        return None
    normalized = GROQ_BASE_URL.strip().rstrip("/")
    if normalized.endswith("/openai/v1"):
        normalized = normalized[: -len("/openai/v1")]
    return normalized or None


def _normalize_search_result(data: Dict[str, Any], corrected_match: str, discipline: str) -> Dict[str, Any]:
    normalized = {
        "match": data.get("match") or corrected_match,
        "discipline": data.get("discipline") or discipline,
        "data_quality": data.get("data_quality") or "poor",
        "confirmed_facts": data.get("confirmed_facts") or [],
        "missing_data": data.get("missing_data") or [],
        "risk_flags": data.get("risk_flags") or [],
        "search_summary": data.get("search_summary") or "",
    }
    if not isinstance(normalized["confirmed_facts"], list):
        normalized["confirmed_facts"] = []
    if not isinstance(normalized["missing_data"], list):
        normalized["missing_data"] = []
    if not isinstance(normalized["risk_flags"], list):
        normalized["risk_flags"] = []
    return normalized


async def collect_project_bundle(match_text: str, discipline: str, date_text: str, league: str = "") -> Dict[str, Any]:
    normalized_discipline = normalize_discipline_label(discipline)
    sides = split_match_text(match_text)
    if len(sides) != 2:
        raise ValueError("Матч должен быть в формате 'Команда 1 vs Команда 2'")

    resolved = resolve_match_entities(sides[0], sides[1], discipline=normalized_discipline)
    match_context = {
        "date": date_text,
        "league": league,
        "sport": "isolated_llm_experiment",
        "home": resolved["team1"]["corrected"],
        "away": resolved["team2"]["corrected"],
    }
    if EXPERIMENT_TAVILY_ONLY:
        facts = build_tavily_only_project_data(
            resolved["match"],
            normalized_discipline,
            date_text,
            league=league,
        )
    else:
        facts = await asyncio.wait_for(
            get_match_data(resolved["match"], normalized_discipline, match_context=match_context),
            timeout=PROJECT_DATA_TIMEOUT,
        )
        deep_search_notes = collect_deep_project_search(resolved["match"], normalized_discipline, date_text)
        facts = f"{facts}{deep_search_notes}"
    annotation = build_annotation_block(resolved["match"])
    return {
        "discipline": discipline,
        "normalized_discipline": normalized_discipline,
        "original_match": match_text,
        "corrected_match": resolved["match"],
        "corrections": resolved,
        "match_context": match_context,
        "annotation": annotation,
        "project_data": facts,
    }


def build_search_stage_input(bundle: Dict[str, Any]) -> str:
    return (
        "EXPERIMENT_MODE: isolated_llm_search\n"
        f"DISCIPLINE: {bundle['discipline']}\n"
        f"MATCH: {bundle['corrected_match']}\n"
        f"DATE: {bundle['match_context'].get('date', '')}\n"
        f"LEAGUE: {bundle['match_context'].get('league', '')}\n\n"
        f"{bundle['annotation']}\n\n"
        "PROJECT_DATA:\n"
        f"{bundle['project_data']}"
    )


def build_analysis_stage_input(bundle: Dict[str, Any], search_result: Dict[str, Any]) -> str:
    return (
        "EXPERIMENT_MODE: isolated_llm_analysis\n"
        f"DISCIPLINE: {bundle['discipline']}\n"
        f"MATCH: {bundle['corrected_match']}\n"
        f"DATE: {bundle['match_context'].get('date', '')}\n"
        f"LEAGUE: {bundle['match_context'].get('league', '')}\n\n"
        "SEARCH_RESULT:\n"
        f"{json.dumps(search_result, ensure_ascii=False, indent=2)}"
    )


async def generate_with_google(contents: str, system_prompt: str) -> str:
    if not GOOGLE_API_KEY or GOOGLE_API_KEY.startswith("your_"):
        raise ValueError("Google API key is missing")

    from google.genai import Client as GoogleClient
    from google.genai import types as genai_types

    client = GoogleClient(
        api_key=GOOGLE_API_KEY,
        http_options=genai_types.HttpOptions(api_version=GOOGLE_API_VERSION),
    )
    model_name = choose_google_model(client, GOOGLE_MODEL)
    request_contents = f"SYSTEM:\n{system_prompt}\n\nUSER:\n{contents}"
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.models.generate_content(model=model_name, contents=request_contents),
    )
    return response.text


def _create_groq_request(client: Any, model_name: str, system_prompt: str, contents: str) -> Any:
    return client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": contents},
        ],
        max_completion_tokens=1600,
        temperature=0.2,
        timeout=45.0,
    )


async def generate_with_groq(contents: str, system_prompt: str) -> str:
    if not GROQ_API_KEY:
        raise ValueError("Groq API key is missing")

    from groq import Client as GroqClient

    client = GroqClient(api_key=GROQ_API_KEY, base_url=_resolve_groq_base_url())
    loop = asyncio.get_event_loop()
    models_to_try = [GROQ_MODEL] + [model for model in GROQ_STABLE_MODELS if model != GROQ_MODEL]

    last_error: Optional[Exception] = None
    for model_name in models_to_try:
        try:
            response = await loop.run_in_executor(
                None,
                _create_groq_request,
                client,
                model_name,
                system_prompt,
                contents,
            )
            if response.choices and response.choices[0].message.content:
                return response.choices[0].message.content
            raise ValueError(f"Groq model {model_name} returned empty response")
        except Exception as exc:
            last_error = exc
            logger.warning("Groq model %s failed: %s", model_name, exc)

    if last_error:
        raise last_error
    raise ValueError("Groq returned empty response")


async def generate_with_deepseek(contents: str, system_prompt: str) -> str:
    if not DEEPSEEK_API_KEY:
        raise ValueError("DeepSeek API key is missing")

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    response = await client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": contents},
        ],
        max_completion_tokens=2000,
        temperature=0.2,
        timeout=45.0,
    )
    if response.choices and response.choices[0].message.content:
        return response.choices[0].message.content
    raise ValueError("DeepSeek returned empty response")


async def generate_with_fallback(contents: str, system_prompt: str, stage_name: str) -> Dict[str, Any]:
    handlers: Dict[str, Callable[[str, str], Any]] = {
        "deepseek": generate_with_deepseek,
        "google": generate_with_google,
        "groq": generate_with_groq,
    }
    last_error: Optional[Exception] = None

    logger.info("%s fallback order: %s", stage_name, " -> ".join(LLM_FALLBACK_ORDER))

    for provider_name in LLM_FALLBACK_ORDER:
        handler = handlers[provider_name]
        try:
            logger.info("Trying %s provider for %s", provider_name, stage_name)
            text = await handler(contents, system_prompt)
            if text and text.strip():
                return {"provider": provider_name, "text": text}
            raise ValueError(f"{provider_name} returned empty response")
        except Exception as exc:
            last_error = exc
            logger.warning("%s provider failed for %s: %s", provider_name, stage_name, exc)

    if last_error:
        raise last_error
    raise ValueError(f"No provider succeeded for {stage_name}")


async def run_llm_search_stage(bundle: Dict[str, Any]) -> Dict[str, Any]:
    search_input = build_search_stage_input(bundle)
    raw_result = await asyncio.wait_for(
        generate_with_fallback(search_input, SEARCH_STAGE_SYSTEM_PROMPT, "llm_search"),
        timeout=SEARCH_STAGE_TIMEOUT,
    )
    parsed = _extract_json_object(raw_result["text"])
    normalized = _normalize_search_result(parsed, bundle["corrected_match"], bundle["discipline"])
    return {
        "provider": raw_result["provider"],
        "raw_text": raw_result["text"],
        "structured": normalized,
    }


async def run_llm_analysis_stage(bundle: Dict[str, Any], search_result: Dict[str, Any]) -> Dict[str, Any]:
    analysis_input = build_analysis_stage_input(bundle, search_result)
    raw_result = await asyncio.wait_for(
        generate_with_fallback(analysis_input, ANALYSIS_STAGE_SYSTEM_PROMPT, "llm_analysis"),
        timeout=ANALYSIS_STAGE_TIMEOUT,
    )
    return {
        "provider": raw_result["provider"],
        "text": raw_result["text"],
    }


async def run_experiment(
    match_text: str,
    discipline: str,
    date_text: str,
    league: str = "",
    run_search_stage: bool = True,
    run_analysis_stage: bool = True,
) -> Dict[str, Any]:
    bundle = await collect_project_bundle(match_text, discipline, date_text, league=league)
    result: Dict[str, Any] = {
        "mode": "isolated_llm_search_analysis",
        "bundle": bundle,
        "configured_provider_hint": LLM_PROVIDER,
    }

    if run_search_stage:
        try:
            search_stage = await run_llm_search_stage(bundle)
            result["llm_search"] = search_stage
        except Exception as exc:
            logger.error("LLM search stage failed: %s", exc)
            result["llm_search_error"] = str(exc)
            result["llm_search"] = {
                "provider": None,
                "raw_text": "",
                "structured": {
                    "match": bundle["corrected_match"],
                    "discipline": bundle["discipline"],
                    "data_quality": "poor",
                    "confirmed_facts": [],
                    "missing_data": ["LLM search stage failed"],
                    "risk_flags": ["search_stage_error"],
                    "search_summary": "LLM search stage did not return valid structured facts.",
                },
            }

    if run_analysis_stage:
        search_payload = result.get("llm_search", {}).get("structured")
        if not search_payload:
            raise ValueError("Analysis stage requires search stage output")
        try:
            result["llm_analysis"] = await run_llm_analysis_stage(bundle, search_payload)
        except Exception as exc:
            logger.error("LLM analysis stage failed: %s", exc)
            result["llm_analysis_error"] = str(exc)

    return result


async def _main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Isolated LLM search -> LLM analysis experiment")
    parser.add_argument("--match", required=True, help="Match in format 'Team A vs Team B'")
    parser.add_argument("--discipline", required=True, help="Discipline name")
    parser.add_argument("--date", required=True, help="Match date")
    parser.add_argument("--league", default="", help="League or tournament")
    parser.add_argument("--search-only", action="store_true", help="Run only the LLM search stage after project data collection")
    parser.add_argument("--analysis-only", action="store_true", help="Run both stages but print only the analysis block")
    args = parser.parse_args()

    result = await run_experiment(
        match_text=args.match,
        discipline=args.discipline,
        date_text=args.date,
        league=args.league,
        run_search_stage=True,
        run_analysis_stage=not args.search_only,
    )

    emit_quiet_e2e_summary(
        match_text=result.get("bundle", {}).get("corrected_match", args.match),
        requested_discipline=result.get("bundle", {}).get("discipline", args.discipline),
        actual_discipline=result.get("bundle", {}).get("normalized_discipline", ""),
        clarification_type=None,
        search_text=result.get("bundle", {}).get("project_data", ""),
        llm_provider=(result.get("llm_analysis") or result.get("llm_search") or {}).get("provider", "unknown"),
        final_text=(result.get("llm_analysis") or {}).get("text") or json.dumps((result.get("llm_search") or {}).get("structured", {}), ensure_ascii=False),
    )

    if args.analysis_only:
        print(json.dumps(result.get("llm_analysis", {}), ensure_ascii=False, indent=2))
        return

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())