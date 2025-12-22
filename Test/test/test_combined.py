from App.generate_sightseeing import generate_sightseeing
from App.itinerary_builder import generate_itinerary


city = "Jaipur"
days = 3

# 1. Generate sightseeing data
sightseeing_data = generate_sightseeing(city, days=days, max_places=6)

sightseeing_list = sightseeing_data.get("sightseeing", [])

# 2. Generate itinerary based on sightseeing
itinerary_data = generate_itinerary(city, days, sightseeing_list)

# 3. Merge results into one travel plan
travel_plan = {
    "city": city,
    "days": days,
    "sightseeing": sightseeing_list,
    "itinerary": itinerary_data.get("itinerary", [])
}

print(travel_plan)
