"""
Understanding what the agent wrote in a city's "Notes / Recommendations" box.

The AI (see generate_sightseeing) copies out the raw phrases; this module turns them into
facts the planner can use, with plain deterministic code so it is predictable and testable:

    arrival_time / arrival_period      when the guests reach THIS city  (morning/afternoon/evening/night/unknown)
    departure_time / departure_period  when they leave the trip from this city (matters for the last city)
    transport_mode                     how they reach THIS city (empty = by car, the default)
    transport_to_next                  how they leave this city for the next one (empty = by car)
"""
import re
from typing import Any, Dict, Optional

from feasibility import is_car_mode

PERIODS = ("morning", "afternoon", "evening", "night")

_AMPM = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?)(?![a-z])", re.I)
_H24 = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_PERIOD_WORDS = (
    ("night", ("midnight", "late night", "night", "tonight", "after dinner")),
    ("evening", ("evening", "sunset", "dusk")),
    ("afternoon", ("afternoon", "noon", "lunch")),
    ("morning", ("morning", "sunrise", "breakfast", "early")),
)


def _period_of_hour(hour: float) -> str:
    if hour < 5:
        return "night"
    if hour < 12:
        return "morning"
    if hour < 16:
        return "afternoon"
    if hour < 20:
        return "evening"
    return "night"


def period_from_text(text: Optional[str]) -> str:
    """'9:30 pm' -> 'night', 'around 2 PM' -> 'afternoon', 'late evening' -> 'evening', '' -> 'unknown'."""
    t = (text or "").lower().strip()
    if not t:
        return "unknown"

    m = _AMPM.search(t)
    if m:
        hour = int(m.group(1)) % 12 + (12 if m.group(3).lower().startswith("p") else 0)
        return _period_of_hour(hour + int(m.group(2) or 0) / 60)
    m = _H24.search(t)
    if m:
        return _period_of_hour(int(m.group(1)) + int(m.group(2)) / 60)

    for period, words in _PERIOD_WORDS:
        if any(w in t for w in words):
            return period
    return "unknown"


_MODE = re.compile(
    r"\b(?:by|via|on|take|taking|using)\s+(?:a\s+|an\s+|the\s+)?"
    r"(train|rail|flight|plane|air|bus|volvo|ferry|boat|helicopter|bike|motorbike)\b"
    r"|\b(flight|train|bus|volvo)\s+(?:from|to)\b",
    re.I,
)


def quick_transport_mode(note: Optional[str], to_next: bool = False) -> str:
    """
    Cheap keyword check ('by train', 'flight to ...') used before the AI has read the note,
    e.g. for the early route warnings. Returns '' when no non-car mode is mentioned.
    `to_next=False` looks at how guests reach THIS city; `to_next=True` at clauses about the
    NEXT city ("next city by flight").
    """
    for clause in re.split(r"[.;\n,]+", note or ""):
        if ("next" in clause.lower()) != to_next:
            continue
        m = _MODE.search(clause)
        if m:
            return (m.group(1) or m.group(2)).lower()
    return ""


def _mode(value: Any) -> str:
    """'' for car / unspecified, otherwise the mode as written (e.g. 'train', 'flight')."""
    text = str(value or "").strip()
    return "" if is_car_mode(text) else text


def normalise_note_info(raw: Any) -> Dict[str, str]:
    """Clean the AI's raw phrases into the fields the planner uses. Always returns every key."""
    raw = raw if isinstance(raw, dict) else {}
    arrival = str(raw.get("arrival_time") or "").strip()
    departure = str(raw.get("departure_time") or "").strip()
    return {
        "arrival_time": arrival,
        "arrival_period": period_from_text(arrival),
        "departure_time": departure,
        "departure_period": period_from_text(departure),
        "transport_mode": _mode(raw.get("transport_mode")),
        "transport_to_next": _mode(raw.get("transport_to_next")),
    }


def mode_into_city(index: int, cities: list, infos: Dict[str, Dict[str, str]]) -> str:
    """
    Mode of the transfer INTO cities[index] ('' = car): what its own box says,
    otherwise what the previous city's box says about leaving for the next city.
    """
    if index == 0:
        return ""
    own = (infos.get(cities[index]) or {}).get("transport_mode", "")
    return own or (infos.get(cities[index - 1]) or {}).get("transport_to_next", "")
