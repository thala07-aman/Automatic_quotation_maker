import streamlit as st
from main import generate_sightseeing
from itinerary_builder import generate_itinerary


def main():
    st.set_page_config(page_title="Travel Plan Builder", layout="wide")

    st.title("🧳 Travel Plan Builder")

    st.write("Generate sightseeing and itinerary plans for any destination.")

    # User inputs
    city = st.text_input("City Name", placeholder="Enter city name, e.g., Jaipur")

    days = st.number_input("Number of Days", min_value=1, max_value=30, value=3)

    max_places = st.number_input("Number of Sightseeing Places", min_value=1, max_value=20, value=6)

    # Submit button
    if st.button("Generate Travel Plan"):
        if city.strip() == "":
            st.error("City cannot be empty.")
            return

        with st.spinner("Generating sightseeing recommendations..."):
            sightseeing_data = generate_sightseeing(city, days=int(days), max_places=int(max_places))
            sightseeing_list = sightseeing_data.get("sightseeing", [])

        with st.spinner("Generating itinerary plan..."):
            itinerary_data = generate_itinerary(city, int(days), sightseeing_list)

        travel_plan = {
            "city": city,
            "days": int(days),
            "sightseeing": sightseeing_list,
            "itinerary": itinerary_data.get("itinerary", [])
        }

        st.success("Travel plan generated successfully!")

        # Sightseeing results
        st.subheader("🏞️ Sightseeing Recommendations")
        for spot in sightseeing_list:
            st.markdown(f"**{spot['place']}** – {spot['description']}")

        # Itinerary results
        st.subheader("📅 Day-by-Day Itinerary")
        for day in travel_plan["itinerary"]:
            st.markdown(f"### Day {day['day']}: {day['title']}")
            for activity in day["activities"]:
                st.markdown(f"- {activity}")

        # Show raw JSON
        st.subheader("📦 Raw Data")
        st.json(travel_plan)


if __name__ == "__main__":
    main()
