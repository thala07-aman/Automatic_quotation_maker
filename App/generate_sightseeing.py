import difflib
import json
from typing import Dict, Any

from llm_client import chat


def _same_place(a: str, b: str) -> bool:
    """True if two place names refer to the same place (case, spacing and small spelling differences)."""
    a, b = a.strip().lower(), b.strip().lower()
    if not a or not b:
        return False
    return a == b or a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def merge_note_places(data: Dict[str, Any], max_places: int) -> Dict[str, Any]:
    """
    Put the places the client wrote in the notes first and flag them `must_visit`.
    The popular places fill the remaining slots, so the list is never shorter than the
    number of requested places (it grows beyond `max_places` if the notes need it).
    """
    note_places = []
    for item in data.get("note_places") or []:
        name = str((item.get("place") if isinstance(item, dict) else item) or "").strip()
        if name and not any(_same_place(name, p["place"]) for p in note_places):
            description = (item.get("description") if isinstance(item, dict) else "") or "Requested by the client."
            note_places.append({"place": name, "description": description, "must_visit": True})

    popular = [
        p for p in data.get("sightseeing") or []
        if p.get("place") and not any(_same_place(p["place"], n["place"]) for n in note_places)
    ]
    data["sightseeing"] = note_places + popular[:max(0, max_places - len(note_places))]
    data.pop("note_places", None)
    return data


def generate_sightseeing(note: str ,city: str, days: int = 3, max_places: int = 6, ) -> Dict[str, Any]:
    """
    Generates sightseeing suggestions for a travel quotation.
    Places named in the client's notes come first and are flagged "must_visit".
    Returns structured JSON data.
    """

    prompt = f"""
You are a travel planner writing sightseeing suggestions for a quotation PDF.
Be factual, concise, and realistic.
Do not mention prices, timings, or ticket availability.
Avoid dramatic or promotional language.
Short sentences only.

Task:
Generate a sightseeing list for a client visiting {city} for {days} days.

Client notes for {city} (may be empty):
\"\"\"{note.strip()}\"\"\"

1. "note_places": every attraction, landmark, temple, fort, market, viewpoint, park, beach or
   other place to visit that is named in the client notes. Keep the name as the client wrote it
   (fix obvious spelling only). Ignore hotels, restaurants, food, budgets and general wishes.
   Use an empty list if the notes name no place.
2. "sightseeing": {max_places} well known places of {city}, NOT repeating any note_places.
   Order them by popularity: the city's single most famous, most photographed landmark first.

Return ONLY valid JSON in the following format:

{{
  "city": "{city}",
  "note_places": [
    {{
      "place": "Place name",
      "description": "Single-line description. No line breaks."
    }}
  ],
  "sightseeing": [
    {{
      "place": "Place name",
      "description": "Single-line description. No line breaks."
    }}
  ]
}}

Rules:
- Only use real sightseeing locations
- No invented names
- No markdown
- No lists outside JSON
- No disclaimers
"""


    try:
        raw_output = chat(
            [{"role": "user", "content": prompt}],
            temperature=0,
            json_mode=True,
        )

        data = json.loads(raw_output)

        return merge_note_places(data, max_places)

    except json.JSONDecodeError as e:
        print("⚠️ JSON parsing failed. Returning raw output.")
        return {"raw_output": raw_output if 'raw_output' in locals() else ""}

    except Exception as e:
        print("⚠️ LLM request failed:", str(e))
        return {"error": str(e)}
