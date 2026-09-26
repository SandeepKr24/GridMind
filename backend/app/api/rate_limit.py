"""Per-client request limits for the endpoints that spend money.

`/api/chat` spends LLM tokens, `/api/ingest` spends upstream fetches and
database writes, and report generation spends both. The site is public and
anonymous, so the client's address is the only identity there is.

Counts live in process, like conversations and jobs: one container, and a
restart forgiving everyone is acceptable. Each client holds at most `limit`
timestamps and the number of clients tracked is capped, so a flood of distinct
addresses cannot grow memory without bound.

The address is `request.client.host`. Behind the host's proxy that is the
proxy itself unless uvicorn is told to trust it (FORWARDED_ALLOW_IPS), in which
case uvicorn substitutes the forwarded address. The limiter never reads
X-Forwarded-For itself: anyone can send that header, and trusting it here would
let a caller pick a fresh identity per request.
"""

from __future__ import annotations

import logging
import math
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import HTTPException, Request

from app.config import Settings

logger = logging.getLogger(__name__)

LimitName = Literal["chat", "ingest", "report"]

#: Beyond this many distinct clients, the least recently seen is forgotten.
MAX_TRACKED_CLIENTS = 10_000
MINUTE = 60.0
HOUR = 3600.0


class RateLimiter:
    """A sliding-window log: at most `limit` requests in any `window_seconds`."""

    def __init__(
        self,
        limit: int,
        window_seconds: float,
        *,
        max_clients: int = MAX_TRACKED_CLIENTS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._max_clients = max_clients
        self._clock = clock
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()

    def check(self, client: str) -> float | None:
        """Count a request from `client`, or refuse it.

        Returns None when allowed, otherwise the seconds until a slot frees.
        Refused requests are not counted, so waiting out Retry-After works even
        for a client that kept retrying in the meantime.
        """
        now = self._clock()
        hits = self._hits.get(client)
        if hits is None:
            hits = deque()
            self._hits[client] = hits
            if len(self._hits) > self._max_clients:
                self._hits.popitem(last=False)
        else:
            self._hits.move_to_end(client)

        cutoff = now - self._window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self._limit:
            return hits[0] + self._window - now
        hits.append(now)
        return None


def build_rate_limits(settings: Settings) -> dict[LimitName, RateLimiter]:
    return {
        "chat": RateLimiter(settings.rate_limit_chat_per_minute, MINUTE),
        "ingest": RateLimiter(settings.rate_limit_ingest_per_hour, HOUR),
        "report": RateLimiter(settings.rate_limit_report_per_hour, HOUR),
    }


def rate_limit(name: LimitName) -> Callable[[Request], Awaitable[None]]:
    """A route dependency enforcing the limiter called `name`."""

    async def enforce(request: Request) -> None:
        limiter: RateLimiter = request.app.state.rate_limits[name]
        client = request.client.host if request.client is not None else "unknown"
        wait = limiter.check(client)
        if wait is None:
            return
        # No address in the log: it identifies a person and adds nothing here.
        logger.info("rate limit reached on %s", name)
        raise HTTPException(
            429,
            detail="Too many requests. Try again shortly.",
            headers={"Retry-After": str(max(1, math.ceil(wait)))},
        )

    return enforce
