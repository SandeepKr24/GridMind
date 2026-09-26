"""`plain_text`: the model's typographic spacing, turned into plain characters.

gpt-oss writes narrow no-break spaces (U+202F) between first names and
surnames, and non-breaking hyphens (U+2011). On the page they render as odd,
uneven gaps. Test strings build those characters with chr() so the source
holds no invisible characters.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.api.schemas.report import ReportOut
from app.llm.groq import parse_completion
from app.llm.text import plain_text
from tests.test_reports_route import STORED

NARROW = chr(0x202F)
NB_HYPHEN = chr(0x2011)


@pytest.mark.parametrize(
    ("code_point", "replacement"),
    [
        (0x202F, " "),  # narrow no-break space
        (0x00A0, " "),  # no-break space
        (0x2009, " "),  # thin space
        (0x200A, " "),  # hair space
        (0x2007, " "),  # figure space
        (0x2011, "-"),  # non-breaking hyphen
        (0x2010, "-"),  # hyphen
        (0x200B, ""),  # zero-width space
    ],
)
def test_odd_spacing_becomes_plain(code_point: int, replacement: str) -> None:
    assert plain_text(f"Max{chr(code_point)}Verstappen") == f"Max{replacement}Verstappen"


def test_real_punctuation_is_kept() -> None:
    # Apostrophe U+2019, en dash U+2013, em dash U+2014.
    text = f"Hamilton{chr(0x2019)}s win {chr(0x2013)} by 0.647s {chr(0x2014)} was his 105th."
    assert plain_text(text) == text


def test_every_completion_is_cleaned() -> None:
    message = {"content": f"Max{NARROW}Verstappen won."}
    payload = {"choices": [{"message": message, "finish_reason": "stop"}]}
    assert parse_completion(payload, fallback_model="m", latency_ms=1).text == "Max Verstappen won."


def test_reports_stored_before_the_fix_are_cleaned_when_read() -> None:
    section = {
        "heading": f"Race{NARROW}Overview",
        "body": f"Max{NARROW}Verstappen won a one{NB_HYPHEN}stop race.",
    }
    stored = dataclasses.replace(STORED, sections=[section])
    out = ReportOut.from_stored(stored).sections[0]
    assert out.heading == "Race Overview"
    assert out.body == "Max Verstappen won a one-stop race."
