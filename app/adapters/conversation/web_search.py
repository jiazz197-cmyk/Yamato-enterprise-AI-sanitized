"""Web-search adapter (Tavily) — replaces the Dify SearXNG plugin.

Implemented with ``httpx`` directly against the Tavily REST API so the project
does not need to add ``langchain-community`` as a dependency. The langchain
backbone (LCEL chains) drives the LLM steps; web search is a pluggable tool
behind ``WebSearchPort``.

Returns a list of ``{title, content, url}`` dicts, matching the shape the
domain ``filter_by_relevance`` / ``filter_by_time`` helpers expect.
"""

from __future__ import annotations

import logging
from typing import Any, List

from app.core.config import settings
from app.core.http_client import get_http_client

logger = logging.getLogger(__name__)

_TAVILY_URL = "https://api.tavily.com/search"

# Map the Dify "month" time range hint to Tavily's accepted values.
_TIME_RANGE_MAP = {
    "day": "day",
    "week": "week",
    "month": "month",
    "year": "year",
}


class TavilyWebSearchAdapter:
    """Implements ``WebSearchPort`` via the Tavily search API."""

    def __init__(self, api_key: str | None = None, max_results: int = 15):
        self._api_key = api_key or settings.TAVILY_API_KEY
        self._max_results = max_results

    async def search(self, query: str, time_range: str = "month") -> List[dict[str, Any]]:
        if not self._api_key:
            logger.warning("Tavily search skipped: TAVILY_API_KEY not configured")
            return []

        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": self._max_results,
            "search_depth": "advanced",
            "time_range": _TIME_RANGE_MAP.get(time_range, "month"),
        }

        try:
            client = await get_http_client()
            response = await client.post(_TAVILY_URL, json=payload, timeout=20)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.warning("Tavily search failed for query=%r: %s", query[:80], e)
            return []

        results = data.get("results", []) if isinstance(data, dict) else []
        # Normalize to {title, content, url} for the domain filters.
        return [
            {
                "title": r.get("title", ""),
                "content": r.get("content", ""),
                "url": r.get("url", ""),
            }
            for r in results
            if isinstance(r, dict)
        ]
