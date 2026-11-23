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


def ensure_places_in_itinerary(
        days_list: List[Dict[str, Any]], places: List[str], must_places: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Guarantee that the itinerary and the sightseeing list agree:
      * every day's `landmarks` / `key_landmark` uses an exact sightseeing place name;
      * every sightseeing place appears in at least one day's activities
        (missing ones are added as a "Visit <place>" activity on the lightest day);
      * must-visit places (taken from the client's notes) are listed first in `landmarks`
        and become the day's `key_landmark`, so they get photos before anything else.
    """
    if not days_list or not places:
        return days_list
    must = [p for p in (must_places or []) if p in places]

    # 1. Canonical landmark names; fill from places the activities already mention
    for day in days_list:
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
        day["landmarks"] = sorted(landmarks, key=lambda p: p not in must)
        key = _match_place(day.get("key_landmark"), places)
        if day["landmarks"] and day["landmarks"][0] in must:
            key = day["landmarks"][0]
        day["key_landmark"] = key or (day["landmarks"][0] if day["landmarks"] else day.get("key_landmark"))

    # 2. Any place not mentioned anywhere gets added to a day (must-visit places first)
    all_text = " ".join(" ".join(d.get("activities") or []) for d in days_list).lower()
    # arrival / departure days are light, so use them only when there are few days
    order = list(range(len(days_list)))
    if len(days_list) > 2:
        order = order[1:-1]
    for place in must + [p for p in places if p not in must]:
        if place.lower() in all_text:
            continue
        # spread must-visit places over the days so each one can get a photo
        target = days_list[min(order, key=lambda i: (
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
        all_text += f" visit {place.lower()}"
        print(f"Itinerary was missing '{place}', added it to '{target.get('title')}'")
    return days_list


def generate_itinerary(
        city: str,
        days: int,
        sightseeing_list: List[Dict[str, str]],
        cost_per_day_total: float = 0,
        cost_per_day_hotel: float = 0,
        cost_per_day_car: float = 0
) -> Dict[str, Any]:
    """
    Generates a structured day-wise itinerary with detailed activities
    and specific landmarks for each day.
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

    prompt = f"""
You are an experienced travel planner creating a detailed day-by-day itinerary for {city}.

Available Attractions:
{sightseeing_details}

{must_rule}
CRITICAL: Create EXACTLY {days} day(s) itinerary - no more, no less. The itinerary array must contain exactly {days} day objects.

Create a {days}-day itinerary following this structure:

Day 1 Guidelines:
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
- Include buffer time for travel

Important Rules:
1. Use ONLY the attractions listed above, and include EVERY one of them in the itinerary at least once
2. Be specific about activities (e.g., "Visit Taj Mahal at sunrise for best photos")
3. Include practical details (check-in, check-out, transfers)
4. Mention meal times naturally (e.g., "Lunch at local restaurant near Red Fort")
5. Add time-of-day context (morning, afternoon, evening)
6. Keep activities realistic and not rushed
7. Each day should have 4-8 activity items
8. Professional, informative tone
9. Output MUST be valid JSON only, no markdown

Required JSON Format:
{{
  "city": "{city}",
  "itinerary": [
    {{
      "day": 1,
      "title": "Arrival in {city}",
      "activities": [
        "Arrival at airport/railway station",
        "Transfer to hotel",
        "Check-in and freshen up",
        "Evening visit to [landmark]",
        "Dinner at hotel/local restaurant"
      ],
      "key_landmark": "[main attraction for this day]",
      "landmarks": ["[landmark 1]", "[landmark 2]"]
    }},
    {{
      "day": 2,
      "title": "[Descriptive title]",
      "activities": [
        "Morning: [activity]",
        "Visit [landmark 1]",
        "Lunch at [area]",
        "Afternoon: [landmark 2]",
        "Evening: [activity]",
        "Return to hotel"
      ],
      "key_landmark": "[main attraction for this day]",
      "landmarks": ["[landmark 1]", "[landmark 2]"]
    }}
  ]
}}

CRITICAL:
1. Include "key_landmark" field for each day with the main attraction to visit that day.
2. Include "landmarks" array with exactly 2 specific landmarks/attractions that will be visited that day (these should be from the activities list).
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
        
        # every sightseeing place must be in the itinerary, under its exact name
        ensure_places_in_itinerary(
            itinerary_data.get("itinerary", []), [item["place"] for item in sightseeing_list], must_places
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
