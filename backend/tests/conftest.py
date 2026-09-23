"""Test isolation.

Settings read both `backend/.env` and the process environment. Either can
differ between machines and between CI and a laptop, so a test that forgets to
account for them passes here and fails there. Both are cleared for every test;
a test that wants a value provides it explicitly.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.config import Settings

# Every name Settings recognises, as it would appear in the environment.
_SETTING_ENV_NAMES = [name.upper() for name in Settings.model_fields]


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in _SETTING_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    yield
