"""Development entrypoint: `python -m app`.

This exists because uvicorn picks its own event loop. On Windows its
`asyncio_loop_factory()` returns `ProactorEventLoop`, which psycopg refuses:

    Psycopg cannot use the 'ProactorEventLoop' to run in async mode

uvicorn ignores the process-wide policy, so the only way to override it is to
build the Server ourselves and pass a loop factory. On Linux — including the
container we deploy — `event_loop_factory()` returns None and this is an
ordinary uvicorn run.
"""

from __future__ import annotations

import asyncio
import os

import uvicorn

from app.runtime import event_loop_factory


def main() -> None:
    config = uvicorn.Config(
        "app.main:create_app",
        factory=True,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )
    server = uvicorn.Server(config)

    factory = event_loop_factory()
    if factory is None:
        server.run()
    else:
        asyncio.run(server.serve(), loop_factory=factory)


if __name__ == "__main__":
    main()
