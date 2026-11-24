"""
Checks that hotels are billed per NIGHT and the trip length is nights + 1 days.

Scenario from the request: arrive 12 Dec, depart 16 Dec, nights per city "2,1,1"
-> 4 nights / 5 days, hotels billed 2, 1 and 1 nights.

Run from the project root:
    python3 Test/test/nights_check.py
"""
import io
import os
import sys
from datetime import date

from streamlit.testing.v1 import AppTest

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(os.path.dirname(os.path.dirname(HERE)), "App")
DB_PATH = os.path.join(HERE, "_nights_test.db")
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

sys.path.insert(0, APP_DIR)
from feasibility import check_plan  # noqa: E402

# ---------- feasibility: dates vs nights ----------
a, d = date(2026, 12, 12), date(2026, 12, 16)
assert check_plan(["A", "B", "C"], [2, 1, 2], nights_per_city=[2, 1, 1], arrival_date=a, departure_date=d) == [], \
    "12->16 Dec with 2,1,1 nights must be accepted"
msgs = [f["message"] for f in check_plan(["A", "B", "C"], [2, 1, 3], nights_per_city=[2, 1, 2], arrival_date=a, departure_date=d)]
assert any("4 night(s)" in m and "5 night(s)" in m for m in msgs), msgs
print("feasibility dates-vs-nights OK")

# ---------- full app ----------
SCRIPT = '''
import io, sys
sys.path.insert(0, "__APP_DIR__")
import pandas as pd, streamlit as st
import database
database.DB_NAME = "__DB_PATH__"
import llm_client

buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as w:
    rows = []
    for c in ["Agra", "Jaipur", "Delhi"]:
        for i, p in enumerate([3000, 3500, 4000]):
            rows.append({"City": c, "Hotel_Name": "%s H%d" % (c, i), "Star": 4, "Price_Per_Night_Per_Person": p})
    pd.DataFrame(rows).to_excel(w, sheet_name="Hotels", index=False)
    pd.DataFrame({"car_type": ["Sedan"], "price_per_day": [3000]}).to_excel(w, sheet_name="CarRental", index=False)
buf.seek(0)
st.file_uploader = lambda *a, **k: buf
llm_client.chat = lambda *a, **k: "Nice hotel."

SEEN = []
def sight(note, city, days, max_places):
    return {"sightseeing": [{"place": "P", "description": "d"}]}
def itin(city, days, sightseeing_list, cost_per_day_total=0, cost_per_day_hotel=0, cost_per_day_car=0,
         day_plans=None, agent_notes=""):
    SEEN.append((city, days))
    return {"itinerary": [{"day": i + 1, "title": "T%d" % i, "activities": ["x"], "landmarks": ["a", "b"],
                           "key_landmark": "a", "day_cost_total": 1, "hotel_cost": 1, "car_cost": 0} for i in range(days)]}

import travel_plan_app
travel_plan_app.generate_sightseeing = sight
travel_plan_app.generate_itinerary = itin
travel_plan_app.generate_professional_pdf = lambda **k: b"%PDF-fake"
travel_plan_app.build_route = lambda cities: {"cities": [], "legs": [], "missing": []}
st.session_state["_seen_itin"] = SEEN
travel_plan_app.main()
'''.replace("__APP_DIR__", APP_DIR).replace("__DB_PATH__", DB_PATH)

at = AppTest.from_string(SCRIPT, default_timeout=90).run()
assert not at.exception, [e.value for e in at.exception]

at.text_input[0].set_value("Nights Test").run()
at.date_input[0].set_value(date(2026, 12, 12)).run()
at.date_input[1].set_value(date(2026, 12, 16)).run()
at.multiselect[0].set_value(["Agra", "Jaipur", "Delhi"]).run()
nights_box = [t for t in at.text_input if "NIGHTS per city" in t.label][0]
nights_box.set_value("2,1,1").run()
assert not at.exception, [e.value for e in at.exception]

captions = [c.value for c in at.caption]
print("summary caption:", [c for c in captions if "nights" in c])
assert any("4 nights" in c and "5 days" in c for c in captions), captions

warnings = [w.value for w in at.warning] + [e.value for e in at.error]
assert not any("night(s)" in w for w in warnings), warnings
print("no date-mismatch warning for 12->16 Dec with 2,1,1 OK")

at.number_input[[n.label for n in at.number_input].index("Travelers")].set_value(2).run()
[b for b in at.button if "Generate Travel Quotation" in b.label][0].click().run()
assert not at.exception, [e.value for e in at.exception]

# hotel breakdown text per city: rooms x price x NIGHTS
infos = [i.value for i in at.info if "Hotel Pricing Breakdown" in i.value]
for text in infos:
    print(" ", " | ".join(l.strip() for l in text.strip().splitlines() if l.strip()))
nights_in_breakdown = [int(l.split("×")[2].split("nights")[0]) for t in infos for l in t.splitlines() if "- Rooms:" in l]
assert nights_in_breakdown == [2, 1, 1], nights_in_breakdown
print("hotels billed 2,1,1 nights OK")

# total = sum of per-city hotel cost on nights (1 room x price x nights)
expected = 3000 * 1 * 2 + 3000 * 1 * 1 + 3000 * 1 * 1   # cheapest hotel per city, 1 room, price is per room-night here
body = " ".join(m.value for m in at.markdown) + " ".join(w.value for w in at.get("heading"))
grand = [m.value for m in at.markdown if "GRAND TOTAL" in m.value]
print("grand total line:", grand)
assert any(f"{expected:,}" in g for g in grand), (expected, grand)

# itinerary generated for 2 / 1 / 2 days (last city gets the departure day)
seen = at.session_state["_seen_itin"]
print("itinerary days requested:", seen)
assert [d for _, d in seen] == [2, 1, 2], seen

# finalize -> saved record carries both nights and days
[b for b in at.button if "Generate Final Quotation" in b.label][0].click().run()
import json, sqlite3
row = sqlite3.connect(DB_PATH).execute("select quotation_json from quotations").fetchone()
saved = json.loads(row[0])
print("saved nights_per_city:", saved["nights_per_city"], "| days_per_city:", saved["days_per_city"],
      "| pricing nights:", [p["nights"] for p in saved["pricing"].values()])
assert saved["nights_per_city"] == [2, 1, 1] and saved["days_per_city"] == [2, 1, 2]
assert [p["nights"] for p in saved["pricing"].values()] == [2, 1, 1]

# PDF wording
sys.path.insert(0, APP_DIR)
os.environ.setdefault("PEXELS_API_KEY", "")
import image_fetcher
image_fetcher.get_real_image = lambda city, landmark=None, must=False: None  # no network: PDF just omits photos
from pdf_generator import generate_professional_pdf
pdf = generate_professional_pdf(saved, "Nights Test", "QT-TEST", None)
import re
text = b"".join(re.findall(rb"\((.*?)\)\s*Tj", pdf))
print("PDF built:", len(pdf) // 1024, "KB")

# dashboard + clone of the new record, and of an old record (days only)
import dashboard  # noqa: E402
rec = {"quotation_no": "QT-X", "customer_name": "N", "cities": "A", "total_cost": 1, "created_at": "2026-01-01 00:00:00", "data": saved}
assert dashboard.build_clone_prefill(rec)["nights_per_city"] == [2, 1, 1]
old = dict(rec, data={k: v for k, v in saved.items() if k != "nights_per_city"})
old["data"]["days_per_city"] = [3, 2]
assert dashboard.build_clone_prefill(old)["nights_per_city"] == [3, 2], "old records clone with their billed values"
print("clone prefill OK (new + old records)")

os.remove(DB_PATH)
print("ALL OK")
