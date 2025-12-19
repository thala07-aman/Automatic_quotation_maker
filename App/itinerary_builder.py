import os
import json
from typing import Dict, Any, List
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def generate_itinerary(
        city: str,
        days: int,
        sightseeing_list: List[Dict[str, str]],
        cost_per_day_total: float = 0,
        cost_per_day_hotel: float = 0,
        cost_per_day_car: float = 0
) -> Dict[str, Any]:
    """
    Generates a structured day-wise itinerary using sightseeing places
    and applies daily cost labels.
    """

    # format sightseeing places for AI prompt
    sightseeing_names = ", ".join(item["place"] for item in sightseeing_list)

    prompt = f"""
You are a travel planner writing a day-by-day itinerary.
Use ONLY the following sightseeing places: {sightseeing_names}.
Spread them logically across {days} days.

Rules:
- Each day must have a title
- Use short activity lines
- No times, no prices, no random places
- Professional travel tone
- Output must be strict JSON only

Format:
{{
  "city": "{city}",
  "itinerary": [
    {{
      "day": <number>,
      "title": "<title>",
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
        itinerary_data = json.loads(raw_output)

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
