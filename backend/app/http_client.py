"""Shared async HTTP client with retries, used by all ingestion modules."""
import asyncio
from typing import Any

import httpx

from .config import settings

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": settings.user_agent, "Accept": "application/json"},
            follow_redirects=True,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def _get(url: str, params: dict | None = None, retries: int = 2) -> httpx.Response:
    """GET with simple retry/backoff (NWS and NHC return sporadic 5xx)."""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = await get_client().get(url, params=params)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            # A 4xx is a verdict, not a hiccup. Retrying a rejected request
            # cannot change the answer, and against a rate limiter it actively
            # spends more of the quota that caused the rejection.
            if exc.response.status_code < 500:
                raise
            if attempt < retries:
                await asyncio.sleep(1.5 * (attempt + 1))
        except httpx.TransportError as exc:
            last_exc = exc
            if attempt < retries:
                await asyncio.sleep(1.5 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


async def get_json(url: str, params: dict | None = None, retries: int = 2) -> Any:
    return (await _get(url, params, retries)).json()


async def get_bytes(url: str, params: dict | None = None, retries: int = 2) -> bytes:
    return (await _get(url, params, retries)).content


async def get_text(url: str, params: dict | None = None, retries: int = 2) -> str:
    return (await _get(url, params, retries)).text
