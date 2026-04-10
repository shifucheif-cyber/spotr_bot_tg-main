"""Провайдеры поиска: DDG, Serper, Exa, Tavily + загрузка страниц."""

import asyncio
import logging
from typing import Any, Dict, List

import httpx
from bs4 import BeautifulSoup

from services.search_providers.config import (
    EXA_API_KEY,
    REQUEST_HEADERS,
    REQUEST_TIMEOUT,
    SEARCH_ANALYSIS_PROVIDER,
    SEARCH_ANALYSIS_RESULTS_PER_QUERY,
    SERPER_API_KEY,
    TAVILY_API_KEY,
)

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

logger = logging.getLogger(__name__)


# --- Sync executor for legacy bridge ---
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
        return _get_sync_executor().submit(asyncio.run, _fetch_page_excerpt_async(url, entity)).result()
    except RuntimeError:
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


async def search_with_ddgs(query: str, num_results: int = 5, timelimit: str = "m") -> List[Dict[str, Any]]:
    """Search via DuckDuckGo using ddgs library (v9+)."""
    if DDGS is None:
        return []
    try:
        def _do_search():
            ddgs = DDGS()
            kwargs: Dict[str, Any] = {"max_results": num_results}
            if timelimit:
                kwargs["timelimit"] = timelimit
            return ddgs.text(query, **kwargs)
        raw = await asyncio.to_thread(_do_search)
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
        results.append({
            "title": (item.get("title") or "").strip(),
            "body": (item.get("content") or item.get("snippet") or "").strip(),
            "href": (item.get("url") or "").strip(),
            "search_engine": "tavily",
        })
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
