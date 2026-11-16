import json
from typing import Dict, Any

from llm_client import chat


def generate_sightseeing(note: str ,city: str, days: int = 3, max_places: int = 6, ) -> Dict[str, Any]:
    """
    Generates sightseeing suggestions for a travel quotation.
    Returns structured JSON data.
    """

    prompt = f"""
You are a travel planner writing sightseeing suggestions for a quotation PDF.
Be factual, concise, and realistic.
Do not mention prices, timings, or ticket availability.
Avoid dramatic or promotional language.
Short sentences only.

Task:
Generate a sightseeing list for a client visiting {city} for {days} days, and also add the places from {note} if any.
Limit to {max_places} well known places.

Return ONLY valid JSON in the following format:

{{
  "city": "{city}",
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

        return data

    except json.JSONDecodeError as e:
        print("⚠️ JSON parsing failed. Returning raw output.")
        return {"raw_output": raw_output if 'raw_output' in locals() else ""}

    except Exception as e:
        print("⚠️ LLM request failed:", str(e))
        return {"error": str(e)}
