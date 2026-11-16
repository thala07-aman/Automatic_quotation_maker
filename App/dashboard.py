"""
Quotation dashboard: history, filters, insights, clone, and a roadmap of
features that can be plugged in later.

To add a new dashboard feature:
  1. write a `_render_<name>(records_df, ...)` function in this file,
  2. call it from `render_dashboard()`,
  3. flip its entry in FUTURE_FEATURES from "Planned" to "Live" (or remove it).
"""
import json

import pandas as pd
import streamlit as st

from database import get_all_quotations_full, get_quotation, delete_quotation
from route_planner import render_route, render_flags
from pdf_generator import generate_professional_pdf

STAR_OPTIONS = [2, 3, 4, 5]

# Roadmap shown at the bottom of the dashboard. Edit freely.
FUTURE_FEATURES = [
    {
        "name": "Map & route view",
        "description": "Route map, drive times and plan-feasibility warnings. Live in the builder and "
                       "quotation detail. Next: per-landmark distances and a static map in the PDF.",
        "status": "Live (phase 1)",
        "effort": "Medium",
    },
    {
        "name": "Quote status tracking",
        "description": "Draft / Sent / Accepted / Rejected / Expired per quotation, with a validity date "
                       "and a conversion-rate KPI.",
        "status": "Planned",
        "effort": "Low",
    },
    {
        "name": "Markup, taxes & discounts",
        "description": "Agent margin, GST / service tax and discount codes, with an internal view that "
                       "hides the margin from the client PDF.",
        "status": "Planned",
        "effort": "Low",
    },
    {
        "name": "Export to CSV / Excel",
        "description": "Download the filtered quotation list for accounting or reporting.",
        "status": "Planned",
        "effort": "Low",
    },
    {
        "name": "Multi-option comparison PDF",
        "description": "Standard / Premium / Luxury packages side by side in one PDF.",
        "status": "Planned",
        "effort": "Medium",
    },
    {
        "name": "Email & WhatsApp sharing",
        "description": "Send the quotation PDF to the client directly from the dashboard.",
        "status": "Planned",
        "effort": "Medium",
    },
    {
        "name": "Follow-up reminders",
        "description": "Flag quotations with no response after N days and suggest a follow-up message.",
        "status": "Idea",
        "effort": "Medium",
    },
    {
        "name": "Seasonal pricing & date-based hints",
        "description": "Peak / off-season multipliers and a 'cheaper if you travel on...' suggestion.",
        "status": "Idea",
        "effort": "Medium",
    },
    {
        "name": "Client portal link",
        "description": "Shareable web link where the client views the quote, switches hotel options "
                       "and accepts it.",
        "status": "Idea",
        "effort": "High",
    },
    {
        "name": "Team & roles",
        "description": "Per-agent logins, 'my quotations' filter and sales leaderboard.",
        "status": "Idea",
        "effort": "High",
    },
]


# ===============================
# CLONE SUPPORT
# ===============================
def build_clone_prefill(record):
    """Turn a stored quotation into the form defaults used by the 'New Quotation' tab."""
    data = record["data"]
    cities = list(data.get("cities", []))
    days = list(data.get("days_per_city", []))

    # Older records stored a single `hotel_star` instead of a per-city dict.
    stars = data.get("hotel_stars") or {c: data.get("hotel_star") for c in cities}

    sightseeing_counts = [len(v) for v in (data.get("sightseeing") or {}).values()]
    max_places = min(20, max(sightseeing_counts)) if sightseeing_counts else 6

    return {
        "source_no": record["quotation_no"],
        "customer_name": record["customer_name"] or "",
        "cities": cities,
        "days_per_city": days,
        "travelers": data.get("travelers") or 2,
        "stars": {c: s for c, s in stars.items() if s in STAR_OPTIONS},
        "notes": data.get("notes_per_city") or {},
        "max_places": max(1, max_places),
        "rooms": data.get("room_config") or {},
        "cars": data.get("car_details") or {},
    }


def reset_builder_state():
    """Drop all per-session widget/app state so the builder starts clean."""
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def _delete_quotation(quotation_no):
    if delete_quotation(quotation_no):
        # Clear the table selection (row positions shift) and any cached PDF / confirm state
        st.session_state.pop("dash_table", None)
        st.session_state.pop(f"dash_pdf_{quotation_no}", None)
        st.session_state.pop(f"confirm_del_{quotation_no}", None)
        if st.session_state.get("clone_prefill", {}).get("source_no") == quotation_no:
            st.session_state.pop("clone_prefill", None)
        st.toast(f"Deleted {quotation_no}.", icon="🗑️")
    else:
        st.toast(f"{quotation_no} was not found.", icon="⚠️")


def _clone_quotation(quotation_no):
    record = get_quotation(quotation_no)
    if record is None:
        return
    reset_builder_state()
    st.session_state["clone_prefill"] = build_clone_prefill(record)
    st.toast(f"Cloned {quotation_no}. Open the ➕ New Quotation tab to continue.", icon="📋")


# ===============================
# DATA PREP
# ===============================
def _records_to_df(records):
    rows = []
    for r in records:
        data = r["data"]
        days = data.get("days_per_city") or []
        rows.append({
            "Quotation No": r["quotation_no"],
            "Customer": r["customer_name"],
            "Cities": r["cities"],
            "Travelers": data.get("travelers"),
            "Days": sum(days) if days else None,
            "Total (₹)": r["total_cost"] or 0,
            "Created": pd.to_datetime(r["created_at"], errors="coerce"),
        })
    return pd.DataFrame(rows)


# ===============================
# SECTIONS
# ===============================
def _render_kpis(df):
    now = pd.Timestamp.now()
    this_month = df[(df["Created"].dt.year == now.year) & (df["Created"].dt.month == now.month)]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total quotations", len(df))
    c2.metric("Total value quoted", f"₹{df['Total (₹)'].sum():,.0f}")
    c3.metric("Average quotation", f"₹{df['Total (₹)'].mean():,.0f}" if len(df) else "₹0")
    c4.metric("This month", len(this_month))


def _render_filters(df):
    """Return the filtered DataFrame."""
    all_cities = sorted({c.strip() for cell in df["Cities"].dropna() for c in cell.split(",") if c.strip()})

    f1, f2, f3 = st.columns([2, 2, 2])
    search = f1.text_input("Search", placeholder="Customer or quotation no", key="dash_search")
    city_filter = f2.multiselect("Cities", options=all_cities, key="dash_cities")

    min_date = df["Created"].min()
    max_date = df["Created"].max()
    if pd.notna(min_date) and pd.notna(max_date):
        date_range = f3.date_input(
            "Created between",
            value=(min_date.date(), max_date.date()),
            key="dash_dates",
        )
    else:
        date_range = None

    out = df
    if search.strip():
        s = search.strip().lower()
        out = out[
            out["Customer"].fillna("").str.lower().str.contains(s, regex=False)
            | out["Quotation No"].fillna("").str.lower().str.contains(s, regex=False)
        ]
    if city_filter:
        wanted = set(city_filter)
        out = out[out["Cities"].apply(lambda cell: bool(wanted & {c.strip() for c in (cell or "").split(",")}))]
    if date_range and len(date_range) == 2:
        start, end = date_range
        out = out[(out["Created"].dt.date >= start) & (out["Created"].dt.date <= end)]
    return out


def _render_detail(record, company_config):
    data = record["data"]
    qno = record["quotation_no"]

    st.markdown(f"### 🧾 {qno} — {record['customer_name']}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total", f"₹{(record['total_cost'] or 0):,.0f}")
    m2.metric("Travelers", data.get("travelers", "—"))
    m3.metric("Days", sum(data.get("days_per_city") or []) or "—")
    m4.metric("Created", record["created_at"])

    if data.get("arrival_date"):
        st.caption(f"📅 {data.get('arrival_date')} → {data.get('departure_date', '—')}")

    pricing = data.get("pricing") or {}
    if pricing:
        city_rows = [
            {
                "City": city,
                "Days": p.get("days"),
                "Hotel": p.get("hotel_name"),
                "Hotel total (₹)": p.get("hotel_cost_total"),
                "Car total (₹)": p.get("car_cost_total"),
                "City total (₹)": p.get("city_total"),
            }
            for city, p in pricing.items()
        ]
        st.dataframe(pd.DataFrame(city_rows), hide_index=True, use_container_width=True)

    route = data.get("route")
    if route and (route.get("cities") or route.get("legs")):
        with st.expander("🗺️ Route map & travel times"):
            render_route(route)

    saved_flags = data.get("plan_flags") or []
    if saved_flags:
        with st.expander(f"🧭 Plan check ({len(saved_flags)} note(s))"):
            render_flags(saved_flags)


    with st.expander("📅 Itinerary & sightseeing"):
        for city in data.get("cities", []):
            st.markdown(f"**{city}**")
            for day in (data.get("itinerary") or {}).get(city, []):
                st.markdown(f"- *{day.get('title', '')}*: " + "; ".join(day.get("activities", [])))
            notes = (data.get("notes_per_city") or {}).get(city, "").strip()
            if notes:
                st.caption(f"📝 {notes}")

    a1, a2, a3 = st.columns(3)
    a1.button(
        "📋 Clone to new quotation",
        key=f"clone_{qno}",
        on_click=_clone_quotation,
        args=(qno,),
        use_container_width=True,
        type="primary",
    )
    a2.download_button(
        "⬇️ Download JSON",
        data=json.dumps(data, indent=2, default=str),
        file_name=f"{qno}.json",
        mime="application/json",
        key=f"json_{qno}",
        use_container_width=True,
    )

    pdf_key = f"dash_pdf_{qno}"
    if pdf_key not in st.session_state:
        if a3.button("📄 Build PDF", key=f"pdfbtn_{qno}", use_container_width=True):
            try:
                with st.spinner("Building PDF and fetching images..."):
                    st.session_state[pdf_key] = generate_professional_pdf(
                        quotation_data=data,
                        customer_name=record["customer_name"],
                        quotation_no=qno,
                        company_config=company_config,
                    )
                st.rerun()
            except Exception as exc:
                st.error(f"Could not build PDF for this quotation (older records may lack some data): {exc}")
    else:
        a3.download_button(
            "📥 Download PDF",
            data=st.session_state[pdf_key],
            file_name=f"{qno}.pdf",
            mime="application/pdf",
            key=f"pdfdl_{qno}",
            use_container_width=True,
        )

    with st.expander("🗑️ Delete this quotation"):
        st.warning(f"This permanently removes {qno} from the database and cannot be undone.")
        confirmed = st.checkbox("Yes, delete this quotation", key=f"confirm_del_{qno}")
        st.button(
            "🗑️ Delete permanently",
            key=f"delete_{qno}",
            disabled=not confirmed,
            on_click=_delete_quotation,
            args=(qno,),
        )


def _render_insights(df):
    left, right = st.columns(2)

    with left:
        st.markdown("**Most quoted cities**")
        city_counts = (
            df["Cities"].dropna()
            .apply(lambda cell: [c.strip() for c in cell.split(",") if c.strip()])
            .explode()
            .value_counts()
            .head(10)
        )
        if city_counts.empty:
            st.caption("No data yet.")
        else:
            st.bar_chart(city_counts)

    with right:
        st.markdown("**Quotations per month**")
        monthly = df.dropna(subset=["Created"]).groupby(df["Created"].dt.strftime("%Y-%m")).size()
        if monthly.empty:
            st.caption("No data yet.")
        else:
            st.bar_chart(monthly)


def _render_roadmap():
    st.caption("Features planned for this dashboard. Add or edit entries in `FUTURE_FEATURES` (App/dashboard.py).")
    cols = st.columns(3)
    for i, feat in enumerate(FUTURE_FEATURES):
        with cols[i % 3]:
            with st.container(border=True):
                st.markdown(f"**{feat['name']}**")
                st.write(feat["description"])
                st.caption(f"Status: {feat['status']} · Effort: {feat['effort']}")


# ===============================
# ENTRY POINT
# ===============================
def render_dashboard(company_config):
    records = get_all_quotations_full()

    if not records:
        st.info("No quotations saved yet. Finalize one in the ➕ New Quotation tab and it will appear here.")
    else:
        df = _records_to_df(records)
        by_no = {r["quotation_no"]: r for r in records}

        _render_kpis(df)
        st.markdown("---")

        st.subheader("📂 Quotation History")
        filtered = _render_filters(df).reset_index(drop=True)

        if filtered.empty:
            st.warning("No quotations match the filters.")
        else:
            st.caption(f"{len(filtered)} of {len(df)} quotations — select a row to see details.")
            event = st.dataframe(
                filtered,
                hide_index=True,
                use_container_width=True,
                on_select="rerun",
                selection_mode="single-row",
                key="dash_table",
                column_config={
                    "Total (₹)": st.column_config.NumberColumn(format="₹%d"),
                    "Created": st.column_config.DatetimeColumn(format="DD MMM YYYY, HH:mm"),
                },
            )

            selected = event.selection.rows
            if selected:
                st.markdown("---")
                _render_detail(by_no[filtered.loc[selected[0], "Quotation No"]], company_config)

        st.markdown("---")
        st.subheader("📊 Insights")
        _render_insights(df)

    st.markdown("---")
    with st.expander("🚀 Roadmap — upcoming dashboard features"):
        _render_roadmap()
