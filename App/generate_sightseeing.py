import os
import json
from typing import Dict, Any
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


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
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"}
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
