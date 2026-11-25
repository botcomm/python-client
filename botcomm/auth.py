from __future__ import annotations

import base64
import binascii
import json

import aiohttp

from .errors import APIError, BotCommError
from .transport import HTTP_TIMEOUT

AUTH_HOST = "https://oauth.botcomm.app"  # client_credentials token endpoint

REGRANT_RETRY = 10.0  # retry interval after a failed re-grant, seconds
REGRANT_EARLINESS = 60.0  # re-grant this long before expiry, seconds


def sub_from_token(token: str) -> str:
    """Extract the sub claim from a JWT without verifying it (the server is
    the source of the token)."""
    parts = token.split(".")
    if len(parts) != 3:
        raise BotCommError("invalid token format")

    payload = parts[1]
    try:
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(decoded)
    except (binascii.Error, ValueError) as e:
        raise BotCommError(f"failed to decode payload: {e}") from e

    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise BotCommError("sub claim not found in token")
    return sub


def regrant_interval(expires_in: int) -> float:
    return max(float(expires_in) - REGRANT_EARLINESS, REGRANT_RETRY)


async def grant(http: aiohttp.ClientSession, client_id: str, client_secret: str) -> dict:
    form = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
    async with http.post(AUTH_HOST + "/token", data=form, timeout=timeout) as resp:
        body = await resp.text()
        if resp.status != 200:
            raise APIError(resp.status, body.strip())

    tk = json.loads(body)
    token = tk.get("access_token")
    if not token:
        raise BotCommError("empty access token in response")

    return tk
