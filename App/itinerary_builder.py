import os
import json
from typing import Dict, Any, List
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


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
        f"- {item['place']}: {item['description']}"
        for item in sightseeing_list
    ])

    prompt = f"""
You are an experienced travel planner creating a detailed day-by-day itinerary for {city}.

Available Attractions:
{sightseeing_details}

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
1. Use ONLY the attractions listed above
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
      "key_landmark": "[main attraction for this day]"
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
      "key_landmark": "[main attraction for this day]"
    }}
  ]
}}

CRITICAL: Include "key_landmark" field for each day with the main attraction to visit that day.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"}
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
