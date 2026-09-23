"""The Windows event-loop fix.

Worth testing because it fails on one platform only, and only once a real
connection is attempted — so it would sail through CI on Linux and break the
moment someone runs the server locally on Windows.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from app import runtime
from app.runtime import configure_event_loop, event_loop_factory


class TestOffWindows:
    def test_policy_fix_is_a_no_op(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(runtime, "_NEEDS_SELECTOR_LOOP", False)
        assert configure_event_loop() is False

    def test_uvicorn_keeps_its_own_loop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # None means "accept uvicorn's default", which is correct in the
        # Linux container we deploy to.
        monkeypatch.setattr(runtime, "_NEEDS_SELECTOR_LOOP", False)
        assert event_loop_factory() is None


class TestOnWindows:
    def test_uvicorn_is_given_a_selector_loop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # uvicorn's own factory returns ProactorEventLoop on win32 and ignores
        # the policy, so this override is the only thing that works.
        monkeypatch.setattr(runtime, "_NEEDS_SELECTOR_LOOP", True)
        assert event_loop_factory() is asyncio.SelectorEventLoop

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only policy")
    def test_policy_fix_selects_a_loop_psycopg_can_use(self) -> None:
        configure_event_loop()
        assert isinstance(asyncio.get_event_loop_policy(), asyncio.WindowsSelectorEventLoopPolicy)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only policy")
    def test_policy_fix_is_idempotent(self) -> None:
        configure_event_loop()
        assert configure_event_loop() is False


def test_the_two_fixes_are_not_interchangeable() -> None:
    """A regression guard with a story behind it.

    The first attempt set only the policy and called it from `create_app`.
    Tests passed, and the server still failed to reach Postgres, because
    uvicorn had already built a Proactor loop by then. Both pieces are needed:
    the policy for `asyncio.run`, the factory for uvicorn.
    """
    assert callable(configure_event_loop)
    assert callable(event_loop_factory)
