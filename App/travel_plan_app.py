import os

import streamlit as st
import io

from groq import Groq

from generate_sightseeing import generate_sightseeing
from itinerary_builder import generate_itinerary
from pricing_engine import load_pricing_data, get_hotel_price, get_car_price

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ===============================
# SESSION STATE
# ===============================
if "generated" not in st.session_state:
    st.session_state.generated = False

if "city_data" not in st.session_state:
    st.session_state.city_data = {}

if "selected_option" not in st.session_state:
    st.session_state.selected_option = {}



def explain_hotel_choice(city, hotel_name, star):
    prompt = f"""
You are a travel consultant.
Explain in 2 short professional sentences why {hotel_name}, a {star}-star hotel in {city},
is a good choice for travelers.

Rules:
- No pricing
- No exaggeration
- No promises
- Business-professional tone
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )

    return response.choices[0].message.content.strip()


def main():
    st.set_page_config(page_title="Multi-City Travel Builder", layout="wide")
    st.title("🧳 Multi-City Travel Quotation Builder")

    # ------------------------------------------
    # UPLOAD PRICING EXCEL
    # ------------------------------------------
    uploaded_file = st.file_uploader("Upload Pricing Excel File", type=["xlsx"])

    if not uploaded_file:
        st.warning("⚠ Upload Excel file to continue.")
        return

    hotels_df, car_df = load_pricing_data(uploaded_file)

    if hotels_df is None or car_df is None:
        st.error("❌ Excel format must include sheets: Hotels + CarRental")
        return

    # ------------------------------------------
    # CITY SELECTION
    # ------------------------------------------
    unique_cities = sorted(hotels_df["City"].unique().tolist())

    cities = st.multiselect(
        "Select Cities (in order)",
        options=unique_cities,
        help="Example: Delhi → Agra → Jaipur"
    )

    if len(cities) == 0:
        st.info("Select at least one city.")
        return

    # ------------------------------------------
    # DAY INPUT
    # ------------------------------------------
    days_input = st.text_input(
        "Enter comma-separated days per city",
        placeholder="Example: 2,1,3"
    )

    try:
        days_per_city = [int(x.strip()) for x in days_input.split(",")]
    except:
        st.warning("Enter numbers only — like 2,1,3")
        return

    if len(days_per_city) != len(cities):
        st.warning("Number of day values must match number of cities selected.")
        return

    # ------------------------------------------
    # OTHER INPUTS
    # ------------------------------------------
    travelers = st.number_input("Travelers", min_value=1, max_value=20, value=2)
    star = st.selectbox("Hotel Category", options=[2, 3, 4, 5], index=2)
    max_places = st.number_input("Sightseeing places per city", min_value=1, max_value=20, value=6)

    # ------------------------------------------
    # NOTES PER CITY (NEW FEATURE)
    # ------------------------------------------
    st.subheader("📝 Notes / Recommendations Per City (Optional)")
    city_notes = {}

    for city in cities:
        note = st.text_area(
            f"Notes for {city}",
            placeholder=f"Enter recommendations for {city}…"
        )
        city_notes[city] = note

    # ------------------------------------------
    # PROCESS BUTTON
    # ------------------------------------------
    if st.button("Generate Multi-City Quotation"):
        st.session_state.generated = True
        st.session_state.hotel_options = None
        st.session_state.sightseeing = None
        st.session_state.itinerary = None

    if not st.session_state.generated:
        return

    total_cost = 0
    multi_city_pricing = {}
    all_sightseeing = {}
    all_itineraries = {}

    # ------------------------------
    # LOOP PER CITY
    # ------------------------------
    for city, days in zip(cities, days_per_city):

        if city not in st.session_state.city_data:
            # --- pricing ---
            city_hotels = hotels_df[
                (hotels_df["City"].str.lower() == city.lower()) &
                (hotels_df["Star"] == star)
                ].sort_values("Price_Per_Night_Per_Person")

            if city_hotels.empty:
                st.error(f"❌ No hotels found for {city} ({star}-star)")
                return

            hotel_options = city_hotels.head(3).reset_index(drop=True)

            options = []
            for _, row in hotel_options.iterrows():
                options.append({
                    "hotel_name": row["Hotel_Name"],
                    "price": row["Price_Per_Night_Per_Person"],
                    "star": row["Star"],
                    "recommendation": explain_hotel_choice(
                        city, row["Hotel_Name"], row["Star"]
                    )
                })

            st.subheader(f"🏨 Hotel Options — {city}")

            labels = ["Option A (Best Value)", "Option B", "Option C"]

            selected_index = st.radio(
                f"Choose hotel for {city}",
                range(len(options)),
                format_func=lambda i: labels[i],
                key=f"hotel_option_{city}"
            )
            st.session_state.selected_option[city] = selected_index
            selected_hotel = options[selected_index]

            for i, opt in enumerate(options):
                st.markdown(f"### {labels[i]}")
                st.write(f"**{opt['hotel_name']}** ({opt['star']}-Star)")
                st.write(opt["recommendation"])
                st.write(f"Price per night per person: ₹{opt['price']:,}")
                st.markdown("---")

            hotel_name = selected_hotel["hotel_name"]
            hotel_price = selected_hotel["price"]

            car_price = get_car_price(car_df, city)

            hotel_cost_total = hotel_price * travelers * days
            car_cost_total = car_price * days if car_price else 0

            city_total = hotel_cost_total + car_cost_total
            total_cost += city_total

            cost_per_day_total = city_total / days
            cost_per_day_hotel = hotel_cost_total / days
            cost_per_day_car = car_cost_total / days if car_cost_total else 0

            multi_city_pricing[city] = {
                "days": days,
                "hotel_name": hotel_name,
                "hotel_price": hotel_price,
                "car_price": car_price,
                "hotel_cost_total": hotel_cost_total,
                "car_cost_total": car_cost_total,
                "city_total": city_total
            }

            # --- sightseeing ---
            with st.spinner(f"Sightseeing → {city}"):
                sightseeing_data = generate_sightseeing(city_notes[city] , city, days, max_places, )
                sightseeing_list = sightseeing_data.get("sightseeing", [])
                all_sightseeing[city] = sightseeing_list

            # --- itinerary ---
            with st.spinner(f"Itinerary → {city}"):
                itinerary_data = generate_itinerary(
                    city=city,
                    days=days,
                    sightseeing_list=sightseeing_list,
                    cost_per_day_total=cost_per_day_total,
                    cost_per_day_hotel=cost_per_day_hotel,
                    cost_per_day_car=cost_per_day_car
                )
                itinerary_list = itinerary_data.get("itinerary", [])
                all_itineraries[city] = itinerary_list

    st.success("Multi-City Quotation Ready!")

    # ------------------------------------------
    # DISPLAY OUTPUT
    # ------------------------------------------
    st.subheader("💰 Pricing Overview")
    for city in cities:
        data = multi_city_pricing[city]
        st.write(f"### {city} — {data['days']} Days")
        st.write(f"Hotel: {data['hotel_name']} ({star}-Star)")
        st.write(f"Hotel Total: ₹{data['hotel_cost_total']:,}")
        st.write(f"Car Total: ₹{data['car_cost_total']:,}")
        st.write(f"City Total: ₹{data['city_total']:,}")
        if city_notes[city].strip():
            st.write("📝 Notes:")
            st.write(city_notes[city])
        st.markdown("---")

    st.write(f"## GRAND TOTAL: ₹{total_cost:,}")

    st.subheader("🏞️ Sightseeing (City-wise)")
    for city in cities:
        st.markdown(f"### {city}")
        if all_sightseeing[city]:
            for spot in all_sightseeing[city]:
                st.markdown(f"- **{spot['place']}** — {spot['description']}")
        else:
            st.write("No sightseeing available.")
        st.markdown("---")

    st.subheader("📅 Day-by-Day Itinerary (City-wise)")

    day_counter = 1  # running day number across all cities

    for city in cities:
        st.markdown(f"## {city} — {multi_city_pricing[city]['days']} Days")

        for day in all_itineraries[city]:
            st.markdown(f"### Day {day_counter}: {day['title']}")

            for activity in day["activities"]:
                st.markdown(f"- {activity}")

            st.markdown(
                f"💰 **Cost:** ₹{day['day_cost_total']:,} "
                f"(Hotel: ₹{day['hotel_cost']:,}, Car: ₹{day['car_cost']:,})"
            )

            st.markdown("---")
            day_counter += 1

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Travel Quotation", styles["Heading1"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Total Travelers: {travelers}", styles["Normal"]))
    story.append(Paragraph(f"Hotel Category: {star}-Star", styles["Normal"]))
    story.append(Paragraph(f"Grand Total: ₹{total_cost:,}", styles["Heading2"]))
    story.append(Spacer(1, 12))

    for city in cities:
        data = multi_city_pricing[city]
        story.append(Paragraph(f"=== {city} ({data['days']} Days) ===", styles["Heading2"]))
        story.append(Paragraph(f"Hotel: {data['hotel_name']}", styles["Normal"]))
        story.append(Paragraph(f"Hotel Total: ₹{data['hotel_cost_total']:,}", styles["Normal"]))
        story.append(Paragraph(f"Car Total: ₹{data['car_cost_total']:,}", styles["Normal"]))
        story.append(Paragraph(f"City Total: ₹{data['city_total']:,}", styles["Normal"]))
        story.append(Spacer(1, 12))

        if city_notes[city].strip():
            story.append(Paragraph("Notes:", styles["Heading3"]))
            for line in city_notes[city].split("\n"):
                story.append(Paragraph(line, styles["Normal"]))
            story.append(Spacer(1, 12))

        story.append(Paragraph("Sightseeing:", styles["Heading3"]))
        for spot in all_sightseeing[city]:
            story.append(Paragraph(f"{spot['place']}: {spot['description']}", styles["Normal"]))
        story.append(Spacer(1, 12))

        story.append(Paragraph("Itinerary:", styles["Heading3"]))
        for day in all_itineraries[city]:
            story.append(Paragraph(f"Day {day['day']}: {day['title']}", styles["Normal"]))
            for activity in day["activities"]:
                story.append(Paragraph(f"- {activity}", styles["Normal"]))
            story.append(Paragraph(
                f"Day Cost: ₹{day['day_cost_total']:,}",
                styles["Normal"]
            ))
            story.append(Spacer(1, 12))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    st.download_button(
        label="📄 Download PDF Quotation",
        data=pdf_bytes,
        file_name=f"multicity_quotation.pdf",
        mime="application/pdf"
    )


if __name__ == "__main__":
    main()
