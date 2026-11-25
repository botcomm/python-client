from __future__ import annotations


class BotCommError(Exception):
    """Base error of the BotComm SDK."""


class APIError(BotCommError):
    """A non-2xx response from the BotComm API."""

    def __init__(self, status: int, body: str):
        super().__init__(f"{status}: {body}")
        self.status = status
        self.body = body
