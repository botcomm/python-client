from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

import aiohttp

from .errors import APIError

API_HOST = "https://api.botcomm.app"  # resource API

READ_TIMEOUT = 90.0  # silence on the stream (server pings every 30s) treated as a dead connection
HTTP_TIMEOUT = 60.0  # timeout for REST API requests, seconds


async def request(http: aiohttp.ClientSession, access_token: str, method: str, path: str, body: Optional[dict] = None) -> Any:
    """Perform an authenticated JSON request against the API."""
    headers = {
        "Accept": "application/json",
        "Authorization": "Bearer " + access_token,
    }
    kwargs: dict = {"json": body}
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
    for attempt in range(2):
        async with http.request(
            method, API_HOST + path, headers=headers, timeout=timeout, **kwargs
        ) as resp:
            text = await resp.text()
            if resp.status == 429 and attempt == 0:
                try:
                    delay = min(float(resp.headers.get("Retry-After", 1)), 30.0)
                except ValueError:
                    delay = 1.0
                await asyncio.sleep(delay)
                continue
            if not 200 <= resp.status < 300:
                raise APIError(resp.status, text.strip())
            return json.loads(text) if text else None


async def connect(http: aiohttp.ClientSession, access_token: str) -> aiohttp.ClientResponse:
    resp = await http.get(
        API_HOST + "/updates",
        headers={
            "Authorization": "Bearer " + access_token,
            "Accept": "text/event-stream",
        },
        timeout=aiohttp.ClientTimeout(total=None, sock_read=READ_TIMEOUT),
    )
    if resp.status != 200:
        body = await resp.text()
        resp.close()
        raise APIError(resp.status, body.strip())
    return resp
