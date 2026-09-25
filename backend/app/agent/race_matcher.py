"""Match what a user called a race against one season's real calendar.

Deterministic on purpose: the model reports the user's words ("Monza",
"Silverstone", "Spain"), and this module decides which round that is. The
calendar itself is FastF1's, so a renamed event ("Brazilian" became "São
Paulo") or a moved one (the 2026 Spanish GP is in Madrid) is handled by the
data rather than by the model's memory of past seasons.

Matching runs in tiers, and only the best tier that matches anything counts:

1. the event's own name ("british" for the British Grand Prix);
2. an alias for an event's name ("spa" -> belgian, "cota" -> united states);
3. an alias for a venue ("catalunya" -> barcelona, "madring" -> madrid);
4. the event's location or country;
5. a partial match against any of those.

Names outrank places because places are shared: "united states" is the US
Grand Prix's name but also the country of Miami and Las Vegas.

More than one event in the winning tier is a genuine ambiguity — 2020 raced
twice at Silverstone and twice at Spielberg — and the caller asks the user.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from app.ingestion.base import RawEvent

# Words that carry no identity: "the British Grand Prix", "Monza GP".
_NOISE = frozenset({"the", "grand", "prix", "gp", "f1", "formula", "circuit", "race", "of"})
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
#: Below this, a partial match ("it", "usa" inside "russian") is noise.
_MIN_PARTIAL = 4

#: User phrasing -> event names or venues, all in normalised form. Only what
#: tiers 1 and 4 cannot already find from the calendar's own names.
ALIASES: dict[str, frozenset[str]] = {
    key: frozenset(values)
    for keys, values in [
        (("britain", "great britain", "uk", "united kingdom", "england"), ("british",)),
        (("italy",), ("italian",)),
        (("spa", "belgium"), ("belgian",)),
        (("hungary", "hungaroring"), ("hungarian",)),
        (("netherlands", "holland"), ("dutch",)),
        (("japan",), ("japanese",)),
        (("china",), ("chinese",)),
        (("australia", "albert park"), ("australian",)),
        (("austria", "red bull ring"), ("austrian",)),
        (("styria",), ("styrian",)),
        (("canada", "gilles villeneuve"), ("canadian",)),
        (("mexico", "mexican", "hermanos rodriguez"), ("mexican", "mexico city")),
        (("brazil", "brazilian", "interlagos"), ("brazilian", "sao paulo")),
        (
            ("usa", "us", "america", "americas", "cota", "united states of america"),
            ("united states",),
        ),
        (("vegas",), ("las vegas",)),
        (("yas", "uae"), ("abu dhabi",)),
        (("saudi", "saudi arabia"), ("saudi arabian",)),
        (("spain",), ("spanish", "barcelona")),
        (("catalunya", "catalonia", "montmelo"), ("barcelona",)),
        (("madring",), ("madrid",)),
        (("imola", "san marino"), ("emilia romagna",)),
        (("portugal", "portimao", "algarve"), ("portuguese",)),
        (("turkey", "istanbul park"), ("turkish",)),
        (("russia",), ("russian",)),
        (("france", "paul ricard"), ("french",)),
        (("germany",), ("german",)),
        (("losail",), ("qatar",)),
        (("monte carlo",), ("monaco",)),
    ]
    for key in keys
}


def normalise(text: str) -> str:
    """Lowercase, unaccented, punctuation-free, without filler words."""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    words = _NON_ALNUM.sub(" ", ascii_only.lower()).split()
    return " ".join(word for word in words if word not in _NOISE)


def _name_key(event: RawEvent) -> str:
    return normalise(event.event_name)


def _place_keys(event: RawEvent) -> set[str]:
    return {normalise(place) for place in (event.location, event.country) if place}


def _partial(query: str, event: RawEvent) -> bool:
    if len(query) < _MIN_PARTIAL:
        return False
    return any(
        query in key or (len(key) >= _MIN_PARTIAL and key in query)
        for key in {_name_key(event), *_place_keys(event)}
        if key
    )


def match_events(query: str, events: Iterable[RawEvent]) -> list[RawEvent]:
    """The events the query most plausibly names; empty if none, several if tied."""
    wanted = normalise(query)
    if not wanted:
        return []
    candidates = list(events)
    aliases = ALIASES.get(wanted, frozenset())
    tiers = (
        lambda e: _name_key(e) == wanted,
        lambda e: _name_key(e) in aliases,
        lambda e: bool(aliases & _place_keys(e)),
        lambda e: wanted in _place_keys(e),
        lambda e: _partial(wanted, e),
    )
    for tier in tiers:
        matched = [event for event in candidates if tier(event)]
        if matched:
            return matched
    return []
