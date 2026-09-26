"""Plain characters for model-written text.

gpt-oss writes typographic spacing: a narrow no-break space (U+202F) between a
first name and surname, a non-breaking hyphen (U+2011) in "one-stop". Rendered,
they show as uneven gaps, and they also break exact matching against stored
names. Every completion passes through `plain_text` (groq.py), and so do
reports stored before this existed (report schema).

Real punctuation stays: en and em dashes, curly quotes and apostrophes. Code
points are written as numbers so the source holds no invisible characters.
"""

from __future__ import annotations

_PLAIN = str.maketrans(
    {
        0x00A0: " ",  # no-break space
        0x2007: " ",  # figure space
        0x2009: " ",  # thin space
        0x200A: " ",  # hair space
        0x202F: " ",  # narrow no-break space
        0x2010: "-",  # hyphen
        0x2011: "-",  # non-breaking hyphen
        0x200B: None,  # zero-width space
    }
)


def plain_text(text: str) -> str:
    return text.translate(_PLAIN)
