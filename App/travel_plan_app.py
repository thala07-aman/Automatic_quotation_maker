import os

import streamlit as st
import io
import re
from openai import OpenAI

from generate_sightseeing import generate_sightseeing
from itinerary_builder import generate_itinerary
from pricing_engine import load_pricing_data
from pricing_engine import get_car_options

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from database import init_db, save_quotation, get_all_quotations, migrate_schema
from pdf_generator import generate_professional_pdf
from image_fetcher import setup_unsplash_api

# FIX: Configuration constants
DEFAULT_EXTRA_BED_PRICE = 1500
DEFAULT_ROOM_CALCULATION_DIVISOR = 2
AI_CACHE_TTL = 3600  # 1 hour

init_db()
migrate_schema()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ===============================
# SESSION STATE
# ===============================
if "generated" not in st.session_state:
    st.session_state.generated = False

if "city_data" not in st.session_state:
    st.session_state.city_data = {}

if "selected_option" not in st.session_state:
    st.session_state.selected_option = {}

if "price_override" not in st.session_state:
    st.session_state.price_override = {}

if "finalized" not in st.session_state:
    st.session_state.finalized = False

if "quotation_no" not in st.session_state:
    st.session_state.quotation_no = None


def safe_filename(name: str) -> str:
    """
    Convert customer name into a safe filename.
    """
    name = name.strip()
    name = re.sub(r"\s+", "_", name)          # spaces → underscore
    name = re.sub(r"[^a-zA-Z0-9_-]", "", name)  # remove special chars
    return name or "quotation"


@st.cache_data(ttl=AI_CACHE_TTL, show_spinner=False)
def explain_hotel_choice(city, hotel_name, star):
    """
    Generate AI-powered hotel recommendation with error handling.
    Cached for 1 hour to avoid redundant API calls.
    """
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

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        # Fallback if AI fails
        return f"{hotel_name} is a well-rated {star}-star property in {city}. It offers comfortable accommodations suitable for travelers."


def main():
    st.set_page_config(page_title="Multi-City Travel Builder", layout="wide")
    st.title("🧳 Multi-City Travel Quotation Builder")

    # ------------------------------------------
    # SIDEBAR - IMAGE FEATURE INFO
    # ------------------------------------------
    with st.sidebar:
        st.header("⚙️ Settings")
        
        # Check if image APIs are configured
        pexels_key = os.getenv("PEXELS_API_KEY", "")
        unsplash_key = os.getenv("UNSPLASH_ACCESS_KEY", "")
        
        if pexels_key or unsplash_key:
            st.success("✅ Destination images enabled")
            if pexels_key:
                st.caption("🔹 Pexels API: Active")
            if unsplash_key:
                st.caption("🔹 Unsplash API: Active")
            st.caption("PDFs will include beautiful destination photos")
        else:
            with st.expander("🖼️ Enable Destination Images", expanded=False):
                setup_unsplash_api()
        
        st.markdown("---")
        st.caption("💡 Tip: Images are cached for 24 hours to improve performance")

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
    customer_name = st.text_input(
        "Customer Name",
        placeholder="Enter customer name"
    )

    if not customer_name.strip():
        st.error("Customer name is required.")
        st.stop()
    
    # ------------------------------------------
    # TRAVEL DATES
    # ------------------------------------------
    col1, col2 = st.columns(2)
    
    with col1:
        arrival_date = st.date_input(
            "Arrival Date",
            help="Select the arrival date for the trip"
        )
    
    with col2:
        departure_date = st.date_input(
            "Departure Date",
            help="Select the departure date for the trip"
        )
    
    # Validate dates
    if departure_date <= arrival_date:
        st.error("Departure date must be after arrival date.")
        st.stop()

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
        # FIX: Validate days are positive
        if any(d <= 0 for d in days_per_city):
            st.error("Days must be positive numbers (greater than 0)")
            return
    except ValueError:
        st.warning("Enter numbers only — like 2,1,3")
        return

    if len(days_per_city) != len(cities):
        st.warning("Number of day values must match number of cities selected.")
        return

    # ------------------------------------------
    # OTHER INPUTS
    # ------------------------------------------
    travelers = st.number_input("Travelers", min_value=1, max_value=50, value=2, help="Number of people traveling")
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
    if st.button("Generate Travel Quotation"):
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
    room_config = {}  # FIX: Initialize outside loop
    car_details = {}  # FIX: Initialize outside loop

    # FIX: Add progress indicator
    progress_bar = st.progress(0)
    progress_text = st.empty()

    # ------------------------------
    # LOOP PER CITY
    # ------------------------------
    for idx, (city, days) in enumerate(zip(cities, days_per_city)):
        progress_text.text(f"Processing {city}... ({idx + 1}/{len(cities)})")
        progress_bar.progress((idx + 1) / len(cities))

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

            st.subheader("🛏️ Room Configuration")

            rooms = st.number_input(
                f"Number of rooms in {city}",
                min_value=1,
                max_value=10,
                value=max(1, travelers // DEFAULT_ROOM_CALCULATION_DIVISOR),
                key=f"rooms_{city}"
            )

            extra_bed = False
            extra_bed_price = 0

            if travelers > (rooms * 2):
                extra_bed = st.checkbox(
                    f"Add extra bed in {city}",
                    key=f"extra_bed_{city}"
                )

                if extra_bed:
                    extra_bed_price = st.number_input(
                        f"Extra bed price per night in {city}",
                        min_value=0,
                        value=DEFAULT_EXTRA_BED_PRICE,
                        step=100,
                        key=f"extra_bed_price_{city}"
                    )

            st.subheader("💸 Hotel Price Adjustment")

            base_price = selected_hotel["price"]

            override_price = st.number_input(
                f"Override hotel price per night (per person) for {city}",
                min_value=0,
                value=int(base_price),
                step=100,
                key=f"override_{city}"
            )

            # Save override only if changed
            if override_price != base_price:
                st.session_state.price_override[city] = override_price
            else:
                st.session_state.price_override.pop(city, None)

            # FIX: Use expander for better UX
            with st.expander("📋 View All Hotel Options", expanded=False):
                for i, opt in enumerate(options):
                    st.markdown(f"### {labels[i]}")
                    st.write(f"**{opt['hotel_name']}** ({opt['star']}-Star)")
                    st.write(opt["recommendation"])
                    st.write(f"Price per night per person: ₹{opt['price']:,}")
                    st.markdown("---")

            effective_price = st.session_state.price_override.get(city, selected_hotel["price"])
            hotel_name = selected_hotel["hotel_name"]

            hotel_room_cost = effective_price * rooms * days

            extra_bed_cost = 0
            if extra_bed:
                extra_bed_cost = extra_bed_price * days

            hotel_cost = hotel_room_cost + extra_bed_cost

            if city in st.session_state.price_override:
                st.info(
                    f"Using overridden hotel price: ₹{effective_price:,} "
                    f"(Original: ₹{base_price:,})"
                )

            st.subheader("🚗 Car Requirement")

            want_car = st.checkbox(
                f"Do you want a car in {city}?",
                key=f"want_car_{city}"
            )

            car_type = None
            car_price_per_day = 0
            car_cost = 0

            if want_car:
                car_options = get_car_options(car_df)

                car_type = st.radio(
                    f"Select car type for {city}",
                    options=list(car_options.keys()),
                    key=f"car_type_{city}"
                )

                car_price_per_day = car_options[car_type]
                car_cost = car_price_per_day

                st.info(
                    f"{car_type}: ₹{car_price_per_day:,} per day × {days} days = ₹{car_cost:,}"
                )
            else:
                st.info("No car selected for this city.")

            hotel_cost_total = hotel_cost
            car_cost_total = car_cost * days if car_cost else 0

            city_total = hotel_cost_total + car_cost_total
            total_cost += city_total

            cost_per_day_total = city_total / days
            cost_per_day_hotel = hotel_cost_total / days
            cost_per_day_car = car_cost_total / days if car_cost_total else 0

            st.info(
                f"""
                Hotel Pricing Breakdown for {city}:
                - Rooms: {rooms} × ₹{effective_price:,} × {days} nights = ₹{hotel_room_cost:,}
                - Extra Bed: ₹{extra_bed_price:,} × {days} nights = ₹{extra_bed_cost:,}
                """
            )

            # FIX: Store room and car config per city
            room_config[city] = {
                "rooms": rooms,
                "extra_bed": extra_bed,
                "extra_bed_cost_per_night": extra_bed_price,
                "extra_bed_total_cost": extra_bed_cost
            }
            
            car_details[city] = {
                "required": want_car,
                "car_type": car_type,
                "price_per_day": car_price_per_day,
                "total_car_cost": car_cost_total
            }

            multi_city_pricing[city] = {
                "days": days,
                "hotel_name": hotel_name,
                "base_price": selected_hotel["price"],
                "final_price": st.session_state.price_override.get(city, selected_hotel["price"]),
                "car_price": car_cost,
                "hotel_cost_total": hotel_cost_total,
                "car_cost_total": car_cost_total,
                "city_total": city_total,
                # FIX: Add room and car details for PDF generation
                "rooms": rooms,
                "extra_bed": extra_bed,
                "extra_bed_price": extra_bed_price,
                "extra_bed_cost": extra_bed_cost,
                "hotel_cost": hotel_cost,
                "want_car": want_car,
                "car_type": car_type,
                "car_price_per_day": car_price_per_day,
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

    # FIX: Clear progress indicators
    progress_bar.empty()
    progress_text.empty()
    
    st.success("✅ Multi-City Quotation Ready!")

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

    # ------------------------------------------
    # TRAVEL PLAN JSON
    # ------------------------------------------
    travel_plan = {
        "cities": cities,
        "days_per_city": days_per_city,
        "travelers": travelers,
        "hotel_star": star,
        "sightseeing": all_sightseeing,
        "itinerary": all_itineraries,
        "pricing": multi_city_pricing,
        "total_cost": total_cost,
        "notes_per_city": city_notes,
        "room_config": room_config,  # FIX: Use collected data
        "car_details": car_details,   # FIX: Use collected data
        "arrival_date": arrival_date.strftime("%d %B %Y"),  # Format: 15 January 2026
        "departure_date": departure_date.strftime("%d %B %Y")
    }

    st.markdown("---")
    st.subheader("✅ Finalize Quotation")

    if not st.session_state.finalized:
        if st.button("Generate Final Quotation"):
            quotation_no = save_quotation(
                customer_name=customer_name,
                cities=cities,
                total_cost=total_cost,
                quotation_data=travel_plan
            )

            st.session_state.quotation_no = quotation_no
            st.session_state.finalized = True

            st.success(f"Quotation finalized successfully: {quotation_no}")

    if st.session_state.finalized:
        if st.button("🔄 Create New Quotation"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    # ------------------------------------------
    # PDF GENERATION - PROFESSIONAL STYLE
    # ------------------------------------------
    
    # Company branding configuration (customize as needed)
    company_config = {
        'name': 'TORNADO INDIA',
        'tagline': 'A SIGNATURE OF EXCELLENCE',
        'email': 'info@tornadoindia.in',
        'website': 'www.tornadoindia.in',
        'phone': '+91-8416812989 / +919076797409',
        'watermark': 'TORNADO INDIA'
    }
    
    # Generate professional PDF
    pdf_bytes = generate_professional_pdf(
        quotation_data=travel_plan,
        customer_name=customer_name,
        quotation_no=st.session_state.quotation_no if st.session_state.finalized else "DRAFT",
        company_config=company_config
    )

    # ------------------------------------------
    # PDF DOWNLOAD SECTION
    # ------------------------------------------
    st.markdown("---")
    st.subheader("📥 Download Quotation")
    
    if st.session_state.finalized:
        file_base = safe_filename(customer_name)
        
        col1, col2 = st.columns([3, 1])
        with col1:
            st.success(f"✅ Quotation {st.session_state.quotation_no} is ready for download!")
        with col2:
            st.download_button(
                label="📄 Download PDF",
                data=pdf_bytes,
                file_name=f"{file_base}_{st.session_state.quotation_no}.pdf",
                mime="application/pdf",
                use_container_width=True
            )
    else:
        # Allow preview download before finalizing
        st.info("💡 You can preview the PDF before finalizing the quotation.")
        
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write("Preview PDF (Draft - not saved to database)")
        with col2:
            st.download_button(
                label="👁️ Preview PDF",
                data=pdf_bytes,
                file_name=f"{safe_filename(customer_name)}_DRAFT.pdf",
                mime="application/pdf",
                use_container_width=True
            )

    st.markdown("---")
    st.subheader("📂 Quotation History")

    rows = get_all_quotations()

    if not rows:
        st.info("No quotations saved yet.")
    else:
        for q in rows:
            st.write(
                f"🧾 {q[0]} | 👤 {q[1]} | 📍 {q[2]} | 💰 ₹{q[3]:,} | 🕒 {q[4]}"
            )


if __name__ == "__main__":
    main()
