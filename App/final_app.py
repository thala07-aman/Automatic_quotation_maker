import streamlit as st
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
import io

from main import generate_sightseeing
from itinerary_builder import generate_itinerary
from pricing_engine import load_pricing_data, get_hotel_price, get_car_price


def main():
    st.set_page_config(page_title="Travel Plan Builder", layout="wide")

    st.title("🧳 Travel Plan Builder")
    st.write("Upload your Excel pricing sheet and generate itineraries + quotations.")

    # EXCEL UPLOAD
    uploaded_file = st.file_uploader("Upload Pricing Excel File", type=["xlsx"])

    if not uploaded_file:
        st.warning("⚠ Upload your Excel file to continue.")
        return

    hotels_df, car_df = load_pricing_data(uploaded_file)

    if hotels_df is None or car_df is None:
        st.error("❌ Invalid Excel format. Sheets required: 'Hotels' and 'CarRental'.")
        return

    # USER INPUTS
    city = st.text_input("City Name", placeholder="Enter city, e.g., Jaipur")
    days = st.number_input("Number of Days", min_value=1, max_value=30, value=3)
    travelers = st.number_input("Number of Travelers", min_value=1, max_value=20, value=2)
    star = st.selectbox("Hotel Star Category", options=[2, 3, 4, 5], index=2)
    max_places = st.number_input("Number of Sightseeing Places", min_value=1, max_value=20, value=6)

    # GENERATE BUTTON
    if st.button("Generate Travel Plan"):
        if city.strip() == "":
            st.error("City cannot be empty.")
            return

        # PRICING LOOKUP
        hotel_price_result = get_hotel_price(hotels_df, city, star)
        if hotel_price_result is None:
            st.error("❌ No hotel pricing found for this city/star category.")
            return

        hotel_price, hotel_name = hotel_price_result
        car_price = get_car_price(car_df, city)

        # PRICING CALCULATION
        hotel_cost_total = hotel_price * travelers * int(days)
        car_cost_total = car_price * int(days) if car_price else 0
        total_cost = hotel_cost_total + car_cost_total

        cost_per_day_hotel = hotel_cost_total / days
        cost_per_day_car = car_cost_total / days if car_cost_total else 0
        cost_per_day_total = cost_per_day_hotel + cost_per_day_car

        # DISPLAY PRICING BLOCK
        st.subheader("💰 Pricing Summary")
        st.write(f"**Hotel:** {hotel_name} ({star}-Star)")
        st.write(f"Hotel per night per person: ₹{hotel_price:,}")
        st.write(f"Hotel total: ₹{hotel_cost_total:,}")

        if car_price:
            st.write(f"Car rental per day: ₹{car_price:,}")
            st.write(f"Car rental total: ₹{car_cost_total:,}")

        st.markdown("---")
        st.write(f"### Total Package Cost: ₹{total_cost:,}")

        # SIGHTSEEING
        with st.spinner("Generating sightseeing list..."):
            sightseeing_data = generate_sightseeing(city, days=int(days), max_places=int(max_places))
            sightseeing_list = sightseeing_data.get("sightseeing", [])

        if not sightseeing_list:
            st.error("❌ AI sightseeing generation failed.")
            return

        # ITINERARY
        with st.spinner("Generating itinerary plan..."):
            itinerary_data = generate_itinerary(
                city=city,
                days=int(days),
                sightseeing_list=sightseeing_list,
                cost_per_day_total=cost_per_day_total,
                cost_per_day_hotel=cost_per_day_hotel,
                cost_per_day_car=cost_per_day_car
            )

        itinerary_list = itinerary_data.get("itinerary", [])

        if not itinerary_list:
            st.error("❌ AI itinerary generation failed.")
            return

        # DISPLAY SIGHTSEEING
        st.subheader("🏞️ Sightseeing")
        for spot in sightseeing_list:
            st.markdown(f"**{spot['place']}** – {spot['description']}")

        # DISPLAY ITINERARY
        st.subheader("📅 Itinerary With Cost")
        for day in itinerary_list:
            st.markdown(f"## Day {day['day']}: {day['title']}")
            for activity in day["activities"]:
                st.markdown(f"- {activity}")
            st.markdown(
                f"💰 Cost: ₹{day['day_cost_total']:,} "
                f"(Hotel: ₹{day['hotel_cost']:,}, Car: ₹{day['car_cost']:,})"
            )
            st.markdown("---")

        # TRAVEL PLAN JSON EXPORT
        travel_plan = {
            "city": city,
            "days": int(days),
            "travelers": int(travelers),
            "hotel_name": hotel_name,
            "hotel_star": star,
            "sightseeing": sightseeing_list,
            "itinerary": itinerary_list,
            "total_cost": total_cost
        }

        # st.subheader("📦 Travel Plan JSON")
        # st.json(travel_plan)

        # ===============================
        # PDF GENERATION (REPORTLAB)
        # ===============================

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []

        # Title
        story.append(Paragraph("Travel Quotation", styles["Heading1"]))
        story.append(Spacer(1, 12))

        # Basic info
        story.append(Paragraph(f"Destination: {city}", styles["Normal"]))
        story.append(Paragraph(f"Travelers: {travelers}", styles["Normal"]))
        story.append(Paragraph(f"Days: {days}", styles["Normal"]))
        story.append(Paragraph(f"Hotel: {hotel_name} ({star}-Star)", styles["Normal"]))
        story.append(Paragraph(f"Total Package Cost: ₹{total_cost:,}", styles["Heading3"]))
        story.append(Spacer(1, 12))

        # Sightseeing
        story.append(Paragraph("Sightseeing", styles["Heading2"]))
        for spot in sightseeing_list:
            story.append(Paragraph(f"{spot['place']}: {spot['description']}", styles["Normal"]))
        story.append(Spacer(1, 12))

        # Itinerary
        story.append(Paragraph("Itinerary", styles["Heading2"]))
        for day in itinerary_list:
            story.append(Paragraph(f"Day {day['day']}: {day['title']}", styles["Heading3"]))
            for activity in day["activities"]:
                story.append(Paragraph(f"- {activity}", styles["Normal"]))
            story.append(Paragraph(
                f"Day Cost: ₹{day['day_cost_total']:,} "
                f"(Hotel: ₹{day['hotel_cost']:,}, Car: ₹{day['car_cost']:,})",
                styles["Normal"]
            ))
            story.append(Spacer(1, 12))

        doc.build(story)
        pdf_bytes = buffer.getvalue()
        buffer.close()

        st.download_button(
            label="📄 Download PDF Quotation",
            data=pdf_bytes,
            file_name=f"{city}_quotation.pdf",
            mime="application/pdf"
        )


if __name__ == "__main__":
    main()
