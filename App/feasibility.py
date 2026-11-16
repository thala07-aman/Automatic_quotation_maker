"""
Feasibility checks for a multi-city plan.

check_plan() is a pure function (no Streamlit, no network). Every argument
except `cities` is optional, so it can run on a partial plan (e.g. route only,
before the itinerary has been generated) and simply skips rules it has no data for.

Each flag is a dict: {"severity": "error" | "warning" | "info", "message": str, "city": str | None}
Thresholds below are planning guidelines, tune them to your own experience.
"""

# ---- thresholds (hours / km) ----
LEG_WARN_HOURS = 5          # a single transfer longer than this gets a warning
LEG_ERROR_HOURS = 8         # ... and above this, an error (consider a flight / overnight stop)
DAY_WARN_HOURS = 11         # estimated total busy hours in one day
DAY_ERROR_HOURS = 13
HOURS_PER_STOP = 1.5        # average time at one sightseeing stop
DAY_OVERHEAD_HOURS = 2      # meals, check-in/out, local transfers
SHORT_STAY_LEG_HOURS = 4    # a 1-day stay after a transfer at least this long is rushed
CAR_NEEDED_KM = 150         # transfers at least this long normally need a car / transport


def _flag(severity, message, city=None):
    return {"severity": severity, "message": message, "city": city}


def _fmt(hours):
    total_minutes = int(round(hours * 60))
    h, m = divmod(total_minutes, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def check_plan(cities, days_per_city=None, legs=None, itinerary=None,
               car_details=None, arrival_date=None, departure_date=None):
    """
    cities:         ordered list of city names
    days_per_city:  list of ints aligned with cities
    legs:           list of {"from","to","km","hours"} between consecutive cities
    itinerary:      {city: [day dicts with optional "landmarks"]}
    car_details:    {city: {"required": bool, ...}}
    arrival_date / departure_date: datetime.date objects
    """
    flags = []
    days_per_city = days_per_city or []
    legs = legs or []
    itinerary = itinerary or {}
    car_details = car_details or {}

    inbound = {leg["to"]: leg for leg in legs}  # leg that arrives INTO each city
    day_counts = dict(zip(cities, days_per_city))

    # --- 1. long transfers + no car -------------------------------------
    for leg in legs:
        hours, km = leg["hours"], leg["km"]
        label = f"{leg['from']} → {leg['to']}"
        if hours > LEG_ERROR_HOURS:
            flags.append(_flag(
                "error",
                f"{label} is about {_fmt(hours)} ({km:,.0f} km) by road. Consider a flight/train or an overnight stop.",
                leg["to"],
            ))
        elif hours > LEG_WARN_HOURS:
            flags.append(_flag(
                "warning",
                f"{label} is a long transfer: about {_fmt(hours)} ({km:,.0f} km).",
                leg["to"],
            ))

        if car_details and km >= CAR_NEEDED_KM:
            has_car = car_details.get(leg["from"], {}).get("required") or car_details.get(leg["to"], {}).get("required")
            if not has_car:
                flags.append(_flag(
                    "warning",
                    f"{label} is {km:,.0f} km but no car is selected in either city, so this transfer isn't priced.",
                    leg["to"],
                ))

    # --- 2. one-day stay right after a long transfer --------------------
    for city, leg in inbound.items():
        if day_counts.get(city) == 1 and leg["hours"] >= SHORT_STAY_LEG_HOURS:
            flags.append(_flag(
                "warning",
                f"{city} has only 1 day but getting there takes about {_fmt(leg['hours'])}, "
                "leaving very little time to see it.",
                city,
            ))

    # --- 3. overloaded days (drive + stops + overhead) ------------------
    day_number = 0
    for city, days in zip(cities, days_per_city):
        city_days = itinerary.get(city) or []
        for i in range(days):
            day_number += 1
            if i >= len(city_days):
                continue
            # The first day in a city (except the very first city) carries the inbound transfer.
            drive = inbound[city]["hours"] if (i == 0 and city in inbound) else 0
            stops = len(city_days[i].get("landmarks") or [])
            total = drive + stops * HOURS_PER_STOP + DAY_OVERHEAD_HOURS
            if total <= DAY_WARN_HOURS:
                continue
            severity = "error" if total > DAY_ERROR_HOURS else "warning"
            detail = (
                f"{_fmt(drive)} drive + {stops} sightseeing stop(s)" if drive
                else f"{stops} sightseeing stop(s)"
            )
            flags.append(_flag(
                severity,
                f"Day {day_number} ({city}) looks too packed: {detail} adds up to about "
                f"{_fmt(total)} of activity (limit {DAY_WARN_HOURS}h).",
                city,
            ))

    # --- 4. dates vs total days ----------------------------------------
    if arrival_date and departure_date and days_per_city:
        total_days = sum(days_per_city)
        span = (departure_date - arrival_date).days
        # Accept either reading of "N days": N calendar days (span == N - 1) or span == N.
        if span not in (total_days, total_days - 1):
            flags.append(_flag(
                "warning",
                f"Arrival and departure are {span} day(s) apart, but the cities add up to {total_days} day(s).",
            ))

    return flags
