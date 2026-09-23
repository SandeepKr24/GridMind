"""`python -m app`.

Small, but it holds the one branch that decides whether the server can reach
Postgres on Windows, so it is worth pinning down.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest

from app import __main__ as entrypoint


class ServerSpy:
    instances: ClassVar[list[ServerSpy]] = []

    def __init__(self, config: Any) -> None:
        self.config = config
        self.ran_directly = False
        ServerSpy.instances.append(self)

    def run(self) -> None:
        self.ran_directly = True

    async def serve(self) -> None:
        return None


@pytest.fixture(autouse=True)
def stub_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    ServerSpy.instances.clear()
    monkeypatch.setattr(entrypoint.uvicorn, "Server", ServerSpy)


def test_uses_uvicorns_own_loop_when_no_override_is_needed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entrypoint, "event_loop_factory", lambda: None)
    entrypoint.main()
    assert ServerSpy.instances[0].ran_directly is True


def test_runs_under_the_supplied_loop_factory_when_one_is_needed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The Windows path. Going through server.run() here would rebuild a
    # Proactor loop and break psycopg, so it must not be used.
    used: list[object] = []

    def fake_run(coro: Any, *, loop_factory: Any = None) -> None:
        used.append(loop_factory)
        coro.close()

    monkeypatch.setattr(entrypoint, "event_loop_factory", lambda: asyncio.SelectorEventLoop)
    monkeypatch.setattr(entrypoint.asyncio, "run", fake_run)

    entrypoint.main()

    assert used == [asyncio.SelectorEventLoop]
    assert ServerSpy.instances[0].ran_directly is False


def test_host_and_port_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(entrypoint, "event_loop_factory", lambda: None)
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "9001")

    entrypoint.main()

    config = ServerSpy.instances[0].config
    assert config.host == "0.0.0.0"
    assert config.port == 9001


def test_binds_to_localhost_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # A dev server should not be reachable from the network unless asked.
    monkeypatch.setattr(entrypoint, "event_loop_factory", lambda: None)
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)

    entrypoint.main()

    config = ServerSpy.instances[0].config
    assert config.host == "127.0.0.1"
    assert config.port == 8000
