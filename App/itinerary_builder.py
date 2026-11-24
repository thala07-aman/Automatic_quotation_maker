import difflib
import json
from typing import Dict, Any, List, Optional

from llm_client import chat

_TAIL_WORDS = ("dinner", "return", "check-out", "check out", "checkout", "departure", "transfer")


def _match_place(name: Optional[str], places: List[str]) -> Optional[str]:
    """Map a landmark name written by the AI back to the exact sightseeing place name."""
    if not name:
        return None
    n = name.strip().lower()
    lowered = {p.lower(): p for p in places}
    if n in lowered:
        return lowered[n]
    for low, original in lowered.items():
        if low in n or n in low:
            return original
    close = difflib.get_close_matches(n, list(lowered), n=1, cutoff=0.75)
    return lowered[close[0]] if close else None


def _cap(max_stops: Optional[List[Optional[int]]], i: int) -> Optional[int]:
    """Sightseeing capacity of day `i` (None = unlimited / unknown, 0 = no sightseeing)."""
    return max_stops[i] if max_stops and i < len(max_stops) else None


def ensure_places_in_itinerary(
        days_list: List[Dict[str, Any]], places: List[str], must_places: Optional[List[str]] = None,
        max_stops: Optional[List[Optional[int]]] = None,
) -> List[Dict[str, Any]]:
    """
    Guarantee that the itinerary and the sightseeing list agree:
      * every day's `landmarks` / `key_landmark` uses an exact sightseeing place name;
      * every must-visit place (taken from the client's notes) appears in at least one day's
        activities, listed first in `landmarks` and used as that day's `key_landmark`;
      * every other sightseeing place appears too, as long as some day has room for it.
    `max_stops` (one entry per day, from logistics.day_constraints) keeps the plan realistic:
    a day with 0 stops (night arrival, early departure...) never gets sightseeing, and a day
    never gets more places than fit.
    """
    if not days_list or not places:
        return days_list
    must = [p for p in (must_places or []) if p in places]

    # 1. Canonical landmark names; fill from places the activities already mention
    for i, day in enumerate(days_list):
        cap = _cap(max_stops, i)
        if cap == 0:    # no-sightseeing day: drop any sightseeing the AI put there anyway
            day["activities"] = [
                a for a in day.get("activities") or [] if not any(p.lower() in a.lower() for p in places)
            ]
            day["landmarks"], day["key_landmark"], day["no_sightseeing"] = [], "", True
            continue

        text = " ".join(day.get("activities") or []).lower()
        landmarks = [m for m in (_match_place(l, places) for l in day.get("landmarks") or []) if m]
        landmarks = list(dict.fromkeys(landmarks))
        for place in must:      # a must-visit place named in the activities is never left out
            if place.lower() in text and place not in landmarks:
                landmarks.append(place)
        for place in places:
            if len(landmarks) >= 2:
                break
            if place.lower() in text and place not in landmarks:
                landmarks.append(place)
        landmarks = sorted(landmarks, key=lambda p: p not in must)
        day["landmarks"] = landmarks[:cap] if cap else landmarks
        key = _match_place(day.get("key_landmark"), places)
        if day["landmarks"] and day["landmarks"][0] in must:
            key = day["landmarks"][0]
        day["key_landmark"] = key or (day["landmarks"][0] if day["landmarks"] else day.get("key_landmark"))
        day["no_sightseeing"] = False

    # 2. Any place not mentioned anywhere gets added to a day that has room (must-visit places first)
    all_text = " ".join(" ".join(d.get("activities") or []) for d in days_list).lower()
    order = list(range(len(days_list)))
    if max_stops is None and len(days_list) > 2:
        order = order[1:-1]     # without constraints, arrival / departure days stay light
    for place in must + [p for p in places if p not in must]:
        if place.lower() in all_text:
            continue
        open_days = [
            i for i in order
            if _cap(max_stops, i) != 0 and (_cap(max_stops, i) is None or len(days_list[i]["landmarks"]) < _cap(max_stops, i))
        ]
        if not open_days:
            if place not in must:
                print(f"No day has room for '{place}', leaving it out")
                continue
            # a requested place is compulsory: use the day with the most room, else the last day
            open_days = [i for i in order if _cap(max_stops, i) != 0] or [len(days_list) - 1]
        # spread must-visit places over the days so each one can get a photo
        target = days_list[min(open_days, key=lambda i: (
            sum(1 for l in days_list[i]["landmarks"] if l in must), len(days_list[i]["landmarks"])
        ))]
        activities = target.setdefault("activities", [])
        pos = len(activities)
        while pos > 0 and any(w in activities[pos - 1].lower() for w in _TAIL_WORDS):
            pos -= 1
        activities.insert(pos, f"Visit {place}")
        if place in must:
            target["landmarks"].insert(0, place)
            target["key_landmark"] = place
        else:
            target["landmarks"].append(place)
            if not target.get("key_landmark"):
                target["key_landmark"] = place
        target["no_sightseeing"] = False
        all_text += f" visit {place.lower()}"
        print(f"Itinerary was missing '{place}', added it to '{target.get('title')}'")
    return days_list


def _day_plan_text(day_plans: List[Dict[str, Any]]) -> str:
    lines = []
    for n, plan in enumerate(day_plans, start=1):
        stops = plan.get("max_stops")
        if stops == 0:
            limit = "NO sightseeing on this day (landmarks must be an empty list)"
        elif stops is None:
            limit = "2-3 sightseeing places"
        else:
            limit = f"at most {stops} sightseeing place(s)"
        hint = f' Suggested title: "{plan["title_hint"]}".' if plan.get("title_hint") else ""
        lines.append(f"- Day {n} [{plan['kind']}]: {plan['guidance']} Sightseeing: {limit}.{hint}")
    return "\n".join(lines)


def generate_itinerary(
        city: str,
        days: int,
        sightseeing_list: List[Dict[str, str]],
        cost_per_day_total: float = 0,
        cost_per_day_hotel: float = 0,
        cost_per_day_car: float = 0,
        day_plans: Optional[List[Dict[str, Any]]] = None,
        agent_notes: str = "",
) -> Dict[str, Any]:
    """
    Generates a structured day-wise itinerary with detailed activities
    and specific landmarks for each day.

    `day_plans` (from logistics.day_constraints, one per day) makes the plan realistic: arrival
    time, drive length between cities, transport mode and departure time decide how much
    sightseeing each day can hold. `agent_notes` is the raw text of the city's notes box.
    """

    # format sightseeing places for AI prompt
    sightseeing_details = "\n".join([
        f"- {item['place']}: {item['description']}" + (" [MUST VISIT - requested by client]" if item.get("must_visit") else "")
        for item in sightseeing_list
    ])
    must_places = [item["place"] for item in sightseeing_list if item.get("must_visit")]
    must_rule = (
        "MUST-VISIT places (requested by the client) - each one MUST appear as its own activity: "
        + ", ".join(must_places) + ".\n"
    ) if must_places else ""

    if day_plans and len(day_plans) == days:
        day_guidelines = (
            "DAY-BY-DAY PLAN. Follow it strictly: it is based on the real road distance between the "
            "cities, the transport mode and the client's arrival / departure timings.\n"
            + _day_plan_text(day_plans)
            + "\nOn days with no sightseeing, do not name any attraction in the activities. "
              "Give clock times for check-out / departure / arrival where the plan mentions them."
        )
    else:
        day_plans = None
        day_guidelines = f"""Day 1 Guidelines:
- Start with "Arrival in {city}"
- Include airport/station transfer
- Hotel check-in
- Light sightseeing or rest (depending on arrival time)
- Evening activity if time permits

Middle Days Guidelines:
- Full day sightseeing
- Include 2-3 major attractions per day
- Add meal breaks (breakfast, lunch, dinner locations)
- Include travel time between locations
- Suggest best times to visit (morning/afternoon/evening)
- Add local experiences (markets, cafes, viewpoints)

Last Day Guidelines:
- Morning sightseeing if time permits
- Hotel check-out
- Departure transfer to airport/station
- Include buffer time for travel"""

    notes_block = (
        f"\nNotes from the travel agent (follow anything relevant, such as occasions or preferences):\n"
        f"\"\"\"{agent_notes.strip()}\"\"\"\n"
    ) if (agent_notes or "").strip() else ""

    prompt = f"""
You are an experienced travel planner creating a detailed day-by-day itinerary for {city}.

Available Attractions:
{sightseeing_details}

{must_rule}{notes_block}
CRITICAL: Create EXACTLY {days} day(s) itinerary - no more, no less. The itinerary array must contain exactly {days} day objects.

Create a {days}-day itinerary following this structure:

{day_guidelines}

Important Rules:
1. Use ONLY the attractions listed above, and include EVERY one of them in the itinerary at least once (unless a day is marked no sightseeing)
2. Be specific about activities (e.g., "Visit Taj Mahal at sunrise for best photos")
3. Include practical details (check-in, check-out, transfers)
4. Mention meal times naturally (e.g., "Lunch at local restaurant near Red Fort")
5. Add time-of-day context (morning, afternoon, evening)
6. Keep the plan realistic and not rushed: never schedule sightseeing after 7:30 PM, and never schedule travel and long sightseeing in the same stretch of time
7. Each day should have 4-8 activity items (3-5 on arrival, transfer and departure days)
8. Professional, informative tone
9. Output MUST be valid JSON only, no markdown
10. Never use the same attraction on two different days

Required JSON Format (this shows the shape only; the content must follow the plan above):
{{
  "city": "{city}",
  "itinerary": [
    {{
      "day": 1,
      "title": "[Descriptive title]",
      "activities": [
        "[activity with time of day]",
        "Visit [landmark]",
        "Dinner at hotel/local restaurant"
      ],
      "key_landmark": "[main attraction for this day, or empty string]",
      "landmarks": ["[landmark 1]", "[landmark 2]"]
    }}
  ]
}}

CRITICAL:
1. Include "key_landmark" field for each day with the main attraction to visit that day ("" when the day has no sightseeing).
2. Include "landmarks" array with the specific landmarks/attractions visited that day, at most 2 (these should be from the activities list; empty list when the day has no sightseeing).
3. "key_landmark", "landmarks" and the activities must use the attraction names EXACTLY as written in the Available Attractions list.
"""

    try:
        raw_output = chat(
            [{"role": "user", "content": prompt}],
            temperature=0,
            json_mode=True,
        )
        itinerary_data = json.loads(raw_output)

        # VALIDATION: Ensure correct number of days
        if "itinerary" in itinerary_data:
            actual_days = len(itinerary_data["itinerary"])
            
            if actual_days > days:
                # Trim excess days
                print(f"Warning: AI generated {actual_days} days instead of {days}. Trimming to {days} days.")
                itinerary_data["itinerary"] = itinerary_data["itinerary"][:days]
            elif actual_days < days:
                # Log warning but continue
                print(f"Warning: AI generated only {actual_days} days instead of {days}.")
        
        # every sightseeing place must be in the itinerary, under its exact name,
        # on a day that actually has time for it
        ensure_places_in_itinerary(
            itinerary_data.get("itinerary", []),
            [item["place"] for item in sightseeing_list],
            must_places,
            max_stops=[p.get("max_stops") for p in day_plans] if day_plans else None,
        )

        # attach cost to each day
        for day in itinerary_data["itinerary"]:
            day["day_cost_total"] = round(cost_per_day_total, 2)
            day["hotel_cost"] = round(cost_per_day_hotel, 2)
            day["car_cost"] = round(cost_per_day_car, 2)

        return itinerary_data

    except json.JSONDecodeError:
        return {"error": "JSON parsing failed", "raw": raw_output}

    except Exception as e:
        return {"error": str(e)}
