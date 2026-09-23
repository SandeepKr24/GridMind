"""Platform quirks that must be settled before any connection is opened.

Currently one: psycopg's async mode cannot run on the event loop Windows uses
by default, and uvicorn selects that loop explicitly rather than following the
process-wide policy. So we need both a policy fix (for scripts and tests that
call `asyncio.run`) and a loop factory (for uvicorn).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Callable

logger = logging.getLogger(__name__)

# psycopg raises InterfaceError on ProactorEventLoop, which is the Windows
# default and what uvicorn's own loop factory returns on win32.
_NEEDS_SELECTOR_LOOP = sys.platform == "win32"


def event_loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    """The loop factory to hand to uvicorn, or None to accept its default.

    uvicorn does not consult the event loop policy: its
    `asyncio_loop_factory()` returns `ProactorEventLoop` on Windows outright.
    Passing a factory is therefore the only way to override it.
    """
    if not _NEEDS_SELECTOR_LOOP:
        return None
    return asyncio.SelectorEventLoop


def configure_event_loop() -> bool:
    """Set a process-wide policy psycopg can use. Returns True if it changed.

    This covers `asyncio.run(...)` in scripts and tests. It does **not** cover
    uvicorn — see `event_loop_factory`.

    No-op on Linux and macOS, including the container we deploy. Idempotent.
    """
    if not _NEEDS_SELECTOR_LOOP:
        return False

    policy = asyncio.get_event_loop_policy()
    if isinstance(policy, asyncio.WindowsSelectorEventLoopPolicy):
        return False

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    logger.debug("switched to WindowsSelectorEventLoopPolicy for psycopg")
    return True
