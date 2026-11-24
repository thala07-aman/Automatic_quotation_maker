"""
Realistic per-day constraints for one city's itinerary (pure functions, no network).

Given where a city sits in the trip (first / last), the road leg that brings the guests
into it, and what the client wrote in the notes (arrival / departure time, transport mode),
`day_constraints()` says for every day:
    kind       "arrival" | "transfer" | "normal" | "departure"
    max_stops  how many sightseeing places fit (None = no limit, 0 = none, rest day)
    guidance   plain-English plan for the AI that writes the itinerary
    title_hint suggested day title (or "")

The first day in every city except the first one is the transfer day: the guests check out of
the previous city and travel in. Car is the default mode between cities.
"""
from typing import Any, Dict, List, Optional

from feasibility import is_car_mode

LATEST_SIGHTSEEING_HOUR = 19.5   # no sightseeing planned after 7:30 PM
CHECKIN_HOURS = 1.0              # check-in + freshen up after reaching the hotel
HOURS_PER_STOP = 1.5
LUNCH_HOURS = 0.75
BREAK_HOURS = 0.5                # tea / washroom break on drives longer than 2.5h

# max sightseeing stops by the period in which the guests arrive / leave
ARRIVAL_STOPS = {"morning": 2, "afternoon": 1, "evening": 0, "night": 0, "unknown": 1}
DEPARTURE_STOPS = {"morning": 0, "afternoon": 1, "evening": 2, "night": 2, "unknown": 1}


def clock(hour: float) -> str:
    """12.0 -> '12:00 PM' (rounded to 15 minutes)."""
    total = int(round(hour * 4)) * 15
    h, m = divmod(total, 60)
    h %= 24
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def _duration(hours: float) -> str:
    total_minutes = int(round(hours * 60))
    h, m = divmod(total_minutes, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def transfer_plan(hours: float) -> Dict[str, Any]:
    """
    How to schedule a road transfer of `hours` driving time.
    Short drives leave late (relaxed check-out around noon); long drives start early.
    """
    if hours <= 2.5:
        style, depart = "relaxed", 12.0
    elif hours <= 5:
        style, depart = "morning", 9.0
    elif hours <= 8:
        style, depart = "early", 6.5
    else:
        style, depart = "very_early", 5.0

    drive = hours + (BREAK_HOURS if hours > 2.5 else 0)
    if depart < 13 and depart + drive > 13:
        drive += LUNCH_HOURS                     # lunch falls inside the drive
    arrive = depart + drive

    free = LATEST_SIGHTSEEING_HOUR - (arrive + CHECKIN_HOURS)
    stops = max(0, int(free // HOURS_PER_STOP))
    stops = min(stops, 2 if hours <= 3.5 else 1 if hours <= 8 else 0)
    return {"style": style, "depart": depart, "arrive": arrive, "max_stops": stops}


def _transfer_guidance(prev: str, city: str, km: float, hours: float, plan: Dict[str, Any]) -> str:
    depart, arrive = clock(plan["depart"]), clock(plan["arrive"])
    road = f"about {km:,.0f} km / {_duration(hours)} of driving"
    style = plan["style"]
    if style == "relaxed":
        start = (f"Relaxed morning in {prev}: breakfast at leisure, check out around {depart} "
                 f"(no need to rush), then drive to {city}")
    elif style == "morning":
        start = f"Breakfast in {prev}, check out and leave around {depart}, then drive to {city}"
    elif style == "early":
        start = (f"Early start: check out and leave {prev} by {depart} (breakfast on the way or packed), "
                 f"then drive to {city}")
    else:
        start = (f"Very early start: leave {prev} by {depart} for a long road journey to {city} "
                 f"(breaks for breakfast and lunch on the way)")
    end = f"Reach {city} around {arrive}, hotel check-in and rest."
    return f"{start} by private car ({road}). {end}"


def _arrival_text(notes: Dict[str, str]) -> str:
    when = (notes.get("arrival_time") or "").strip()
    return f' The client says they arrive: "{when}".' if when else ""


def _arrival_guidance(city: str, period: str, notes: Dict[str, str], by: str = "") -> str:
    via = f" by {by}" if by else ""
    said = _arrival_text(notes)
    if period in ("evening", "night"):
        return (f"The guests reach {city}{via} late ({period}).{said} NO sightseeing on this day: "
                f"pickup and transfer to the hotel, check-in, dinner and rest.")
    if period == "afternoon":
        return (f"The guests reach {city}{via} in the afternoon.{said} Hotel check-in and rest, "
                f"then at most one short evening visit.")
    if period == "morning":
        return (f"The guests reach {city}{via} in the morning.{said} Pickup, hotel (early check-in "
                f"subject to availability, otherwise freshen up and leave luggage), then sightseeing.")
    return (f"Arrival time not given.{said} Pickup{via and ' from the ' + by + ' stop'}, hotel check-in, "
            f"then light sightseeing or rest.")


def day_constraints(days: int, city: str, is_first_city: bool, is_last_city: bool,
                    inbound: Optional[Dict[str, Any]] = None,
                    notes: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """
    Constraints for each of the `days` itinerary days in `city`.

    inbound: {"from", "km", "hours"} road leg from the previous city (None if unknown)
    notes:   parsed client notes (see notes_parser.parse_notes)
    """
    notes = notes or {}
    mode = (notes.get("transport_mode") or "").strip()
    by_car = is_car_mode(mode)
    arrival = notes.get("arrival_period") or "unknown"
    departure = notes.get("departure_period") or "unknown"

    out: List[Dict[str, Any]] = []
    for i in range(days):
        day = {
            "kind": "normal", "max_stops": None, "title_hint": "",
            "guidance": "Full day of sightseeing: 2-3 attractions, with meals and realistic travel time.",
        }

        if i == 0:
            if is_first_city:
                day.update(
                    kind="arrival", title_hint=f"Arrival in {city}",
                    max_stops=ARRIVAL_STOPS[arrival],
                    guidance=_arrival_guidance(city, arrival, notes),
                )
            elif by_car and inbound:
                prev, km, hours = inbound["from"], inbound["km"], inbound["hours"]
                plan = transfer_plan(hours)
                stops = plan["max_stops"]
                guidance = _transfer_guidance(prev, city, km, hours, plan)
                if arrival != "unknown":
                    stops = min(stops, ARRIVAL_STOPS[arrival])
                    guidance += _arrival_text(notes) + " Plan the timings around this."
                if stops == 0:
                    guidance += " NO sightseeing on this day."
                day.update(
                    kind="transfer", title_hint=f"{prev} to {city} by road",
                    max_stops=stops, guidance=guidance,
                )
            elif by_car:
                stops = min(1, ARRIVAL_STOPS[arrival])
                day.update(
                    kind="transfer", title_hint=f"Transfer to {city}", max_stops=stops,
                    guidance=("Breakfast and check-out at the previous city's hotel, private car transfer to "
                              f"{city} with a lunch break, hotel check-in.{_arrival_text(notes)}"
                              + (" NO sightseeing on this day." if stops == 0 else " At most one evening visit.")),
                )
            else:
                day.update(
                    kind="transfer", title_hint=f"Arrival in {city}",
                    max_stops=ARRIVAL_STOPS[arrival],
                    guidance=(f"The client travels to {city} by {mode} (arranged by the client, NOT a road drive). "
                              + _arrival_guidance(city, arrival, notes, by=mode)),
                )

        if is_last_city and i == days - 1:
            said = (notes.get("departure_time") or "").strip()
            said_text = f' The client says they depart: "{said}".' if said else ""
            stops = DEPARTURE_STOPS[departure]
            if departure == "morning":
                text = ("Early departure: breakfast (or packed breakfast), hotel check-out and transfer to the "
                        "airport/station with a safe buffer. NO sightseeing.")
            elif departure == "afternoon":
                text = ("Hotel check-out around noon, at most one short morning visit, lunch, then transfer to "
                        "the airport/station with a safe buffer.")
            elif departure in ("evening", "night"):
                text = ("Leisurely day: sightseeing, hotel check-out around 12 noon (luggage can be kept at "
                        "the hotel), then transfer to the airport/station with a safe buffer.")
            else:
                text = ("Departure day: light morning sightseeing only if time permits, hotel check-out, "
                        "transfer to the airport/station with buffer time.")
            if i == 0:   # same day as arrival: keep the tighter limit
                stops = min(stops, day["max_stops"] if day["max_stops"] is not None else stops)
            day.update(kind="departure" if i else day["kind"], max_stops=stops,
                       title_hint=day["title_hint"] or f"Departure from {city}",
                       guidance=(day["guidance"] + " " if i == 0 else "") + text + said_text)

        out.append(day)
    return out
