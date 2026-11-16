"""
Route planning for multi-city trips.

- Geocodes city names with Nominatim (OpenStreetMap).
- Gets road distance / time / geometry between consecutive cities from OSRM.
- Caches everything in the quotations SQLite DB so each city / city-pair is
  only looked up once and saved quotations never depend on live APIs.
- Falls back to a straight-line estimate when the routing API is unreachable.
- Renders the route as a map + legs table (Streamlit / pydeck).

Public API:
    build_route(cities)  -> {"cities": [...], "legs": [...], "missing": [...]}
    render_route(route)
    render_flags(flags)
    format_hours(hours)
"""
import math
import time

import requests
import streamlit as st

from database import get_connection

COUNTRY = "India"  # appended to city names so "Agra" resolves to the right place
USER_AGENT = "travel-quotation-builder/1.0"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"

REQUEST_TIMEOUT = 10
NOMINATIM_MIN_INTERVAL = 1.1  # Nominatim usage policy: max 1 request / second

# OSRM's public profile ignores traffic, road quality and breaks, so its
# durations are optimistic (Delhi -> Agra comes out ~2.5h vs ~3.5-4h in reality).
ROAD_TIME_FACTOR = 1.3

# Straight-line fallback used when OSRM is unreachable.
FALLBACK_DETOUR_FACTOR = 1.3
FALLBACK_SPEED_KMH = 45

_last_nominatim_call = 0.0


def _ensure_tables(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS geo_cache (
            city_key TEXT PRIMARY KEY,
            lat REAL,
            lon REAL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS route_cache (
            from_key TEXT,
            to_key TEXT,
            km REAL,
            hours REAL,
            geometry TEXT,
            PRIMARY KEY (from_key, to_key)
        )
    """)
    conn.commit()


def _key(city):
    return city.strip().lower()


# ===============================
# GEOCODING
# ===============================
def geocode(city):
    """Return (lat, lon) for a city, or None if it can't be resolved. Successful lookups are cached."""
    global _last_nominatim_call

    conn = get_connection()
    try:
        _ensure_tables(conn)
        row = conn.execute(
            "SELECT lat, lon FROM geo_cache WHERE city_key = ?", (_key(city),)
        ).fetchone()
        if row:
            return row[0], row[1]

        wait = NOMINATIM_MIN_INTERVAL - (time.time() - _last_nominatim_call)
        if wait > 0:
            time.sleep(wait)
        _last_nominatim_call = time.time()

        try:
            resp = requests.get(
                NOMINATIM_URL,
                params={"q": f"{city}, {COUNTRY}", "format": "json", "limit": 1},
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            results = resp.json()
        except (requests.RequestException, ValueError):
            return None

        if not results:
            return None

        lat, lon = float(results[0]["lat"]), float(results[0]["lon"])
        conn.execute(
            "INSERT OR REPLACE INTO geo_cache (city_key, lat, lon) VALUES (?, ?, ?)",
            (_key(city), lat, lon),
        )
        conn.commit()
        return lat, lon
    finally:
        conn.close()


# ===============================
# ROUTING
# ===============================
def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _fallback_leg(a, b):
    km = _haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]) * FALLBACK_DETOUR_FACTOR
    return {
        "from": a["city"],
        "to": b["city"],
        "km": round(km, 1),
        "hours": round(km / FALLBACK_SPEED_KMH, 2),
        "estimated": True,
        "geometry": [[a["lon"], a["lat"]], [b["lon"], b["lat"]]],
    }


def get_leg(a, b):
    """Road leg between two located cities (dicts with city/lat/lon). Never raises."""
    import json

    conn = get_connection()
    try:
        _ensure_tables(conn)
        row = conn.execute(
            "SELECT km, hours, geometry FROM route_cache WHERE from_key = ? AND to_key = ?",
            (_key(a["city"]), _key(b["city"])),
        ).fetchone()
        if row:
            return {
                "from": a["city"], "to": b["city"],
                "km": row[0], "hours": row[1],
                "estimated": False, "geometry": json.loads(row[2]),
            }

        try:
            url = OSRM_URL.format(lon1=a["lon"], lat1=a["lat"], lon2=b["lon"], lat2=b["lat"])
            resp = requests.get(
                url,
                params={"overview": "simplified", "geometries": "geojson"},
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            route = data["routes"][0]
        except (requests.RequestException, ValueError, KeyError, IndexError):
            return _fallback_leg(a, b)

        km = round(route["distance"] / 1000, 1)
        hours = round(route["duration"] / 3600 * ROAD_TIME_FACTOR, 2)
        geometry = route["geometry"]["coordinates"]

        conn.execute(
            "INSERT OR REPLACE INTO route_cache (from_key, to_key, km, hours, geometry) VALUES (?, ?, ?, ?, ?)",
            (_key(a["city"]), _key(b["city"]), km, hours, json.dumps(geometry)),
        )
        conn.commit()
        return {
            "from": a["city"], "to": b["city"],
            "km": km, "hours": hours, "estimated": False, "geometry": geometry,
        }
    finally:
        conn.close()


def build_route(cities):
    """
    Locate every city and build road legs between consecutive cities.
    Cities that cannot be located are listed in "missing" and skipped
    (legs touching them are omitted rather than guessed).
    """
    located = {}
    missing = []
    for city in cities:
        coords = geocode(city)
        if coords:
            located[city] = {"city": city, "lat": coords[0], "lon": coords[1]}
        else:
            missing.append(city)

    legs = []
    for a, b in zip(cities, cities[1:]):
        if a in located and b in located:
            legs.append(get_leg(located[a], located[b]))

    return {
        "cities": [located[c] for c in cities if c in located],
        "legs": legs,
        "missing": missing,
    }


# ===============================
# UI
# ===============================
def format_hours(hours):
    total_minutes = int(round(hours * 60))
    h, m = divmod(total_minutes, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def render_route(route):
    """Map + legs table for a route dict produced by build_route()."""
    import pandas as pd
    import pydeck as pdk

    if route.get("missing"):
        st.warning(f"Could not locate on the map: {', '.join(route['missing'])}")

    points = route.get("cities") or []
    legs = route.get("legs") or []

    if not points:
        st.info("No route to show yet.")
        return

    layers = []
    if legs:
        layers.append(pdk.Layer(
            "PathLayer",
            data=[{"path": leg["geometry"]} for leg in legs],
            get_path="path",
            get_color=[59, 130, 212],
            width_min_pixels=3,
        ))
    layers.append(pdk.Layer(
        "ScatterplotLayer",
        data=points,
        get_position=["lon", "lat"],
        get_fill_color=[220, 53, 69],
        get_radius=1,
        radius_min_pixels=7,
        pickable=True,
    ))
    layers.append(pdk.Layer(
        "TextLayer",
        data=points,
        get_position=["lon", "lat"],
        get_text="city",
        get_size=16,
        get_color=[30, 35, 40],
        get_pixel_offset=[0, -18],
    ))

    if len(points) == 1:
        view = pdk.ViewState(latitude=points[0]["lat"], longitude=points[0]["lon"], zoom=8)
    else:
        coords = [p for leg in legs for p in leg["geometry"]] or [[p["lon"], p["lat"]] for p in points]
        view = pdk.data_utils.compute_view(coords, view_proportion=0.9)

    st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view, tooltip={"text": "{city}"}))

    if legs:
        st.dataframe(
            pd.DataFrame([
                {
                    "From": leg["from"],
                    "To": leg["to"],
                    "Distance (km)": leg["km"],
                    "Drive time": format_hours(leg["hours"]) + (" (estimated)" if leg["estimated"] else ""),
                }
                for leg in legs
            ]),
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            f"Drive times are road estimates (OSRM × {ROAD_TIME_FACTOR} for real-world conditions). "
            "Treat them as a planning guide, not a guarantee."
        )


def render_flags(flags):
    """Show feasibility flags (from feasibility.check_plan) with matching severity."""
    for flag in flags:
        if flag["severity"] == "error":
            st.error(f"⛔ {flag['message']}")
        elif flag["severity"] == "warning":
            st.warning(f"⚠️ {flag['message']}")
        else:
            st.info(f"ℹ️ {flag['message']}")
