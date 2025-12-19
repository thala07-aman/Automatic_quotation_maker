import json
from typing import Dict, Any

from main import client


def generate_itinerary(city: str, days: int, sightseeing_list: list) -> Dict[str, Any]:
    """
    Generates a structured day-wise itinerary using sightseeing places.
    """

    # Convert sightseeing list into bullet-ready text
    sightseeing_strings = ", ".join(
        [item["place"] for item in sightseeing_list]
    )

    prompt = f"""
You are a travel planner creating a day-by-day itinerary for a travel quotation.
The sightseeing locations that MUST be used in the itinerary are:

{sightseeing_strings}

Rules:
- Use only the above places.
- Spread places logically across {days} days.
- Each day must have a clear title.
- Keep activities short & real.
- No timings or prices.
- No invented locations.
- No markdown.

Output format must be STRICT JSON:

{{
  "city": "{city}",
  "itinerary": [
    {{
      "day": <number>,
      "title": "<day_title>",
      "activities": [
        "<activity>"
      ]
    }}
  ]
}}
"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=800
        )

        raw_output = response.choices[0].message.content.strip()

        data = json.loads(raw_output)

        return data

    except json.JSONDecodeError:
        print("⚠️ JSON parsing failed. Returning raw output.")
        return {"raw_output": raw_output}
    except Exception as e:
        print("⚠️ Groq request failed:", str(e))
        return {"error": str(e)}
