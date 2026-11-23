"""
End-to-end check of the builder flow: fill form -> generate -> finalize -> build PDF.
AI calls, route lookup and PDF building are stubbed; the database is a throwaway file.

Run from the project root:
    python3 Test/test/flow_finalize_check.py            # AI output identical on every rerun
    python3 Test/test/flow_finalize_check.py nondet     # AI output different on every rerun (like a real LLM)
"""
import os
import sqlite3
import sys
from datetime import date

from streamlit.testing.v1 import AppTest

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(os.path.dirname(os.path.dirname(HERE)), "App")
DB_PATH = os.path.join(HERE, "_flow_test.db")

NONDET = len(sys.argv) > 1 and sys.argv[1] == "nondet"
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

SCRIPT = '''
import io, random, sys
sys.path.insert(0, "__APP_DIR__")
import pandas as pd, streamlit as st
import database
database.DB_NAME = "__DB_PATH__"
import llm_client
NONDET = __NONDET__

buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as w:
    pd.DataFrame({"City": ["Agra"] * 3, "Hotel_Name": ["A", "B", "C"], "Star": [4] * 3,
                  "Price_Per_Night_Per_Person": [3000, 3500, 4000]}).to_excel(w, sheet_name="Hotels", index=False)
    pd.DataFrame({"car_type": ["Sedan"], "price_per_day": [3000]}).to_excel(w, sheet_name="CarRental", index=False)
buf.seek(0)
st.file_uploader = lambda *a, **k: buf
llm_client.chat = lambda *a, **k: "Nice hotel."

def sight(note, city, days, max_places):
    n = random.randint(0, 10**6) if NONDET else 1
    return {"sightseeing": [{"place": "P%d" % n, "description": "d"}]}

def itin(city, days, sightseeing_list, cost_per_day_total=0, cost_per_day_hotel=0, cost_per_day_car=0):
    return {"itinerary": [{"day": i + 1, "title": "T%d" % (random.randint(0, 10**6) if NONDET else i),
                           "activities": ["x"], "landmarks": ["a", "b"], "key_landmark": "a",
                           "day_cost_total": 1, "hotel_cost": 1, "car_cost": 0} for i in range(days)]}

def fake_pdf(**k):
    return b"%PDF-fake"

import travel_plan_app
travel_plan_app.generate_sightseeing = sight
travel_plan_app.generate_itinerary = itin
travel_plan_app.generate_professional_pdf = fake_pdf
travel_plan_app.build_route = lambda cities: {"cities": [], "legs": [], "missing": []}
travel_plan_app.main()
'''.replace("__APP_DIR__", APP_DIR).replace("__DB_PATH__", DB_PATH).replace("__NONDET__", repr(NONDET))

at = AppTest.from_string(SCRIPT, default_timeout=60).run()
print("load exceptions:", [e.value for e in at.exception])


def btn(label):
    found = [b for b in at.button if label in b.label]
    return found[0] if found else None


def downloads():
    return [d.proto.label for d in at.get("download_button")]


at.text_input[0].set_value("Flow Test").run()
at.date_input[0].set_value(date(2026, 3, 1)).run()
at.date_input[1].set_value(date(2026, 3, 3)).run()
at.multiselect[0].set_value(["Agra"]).run()
[t for t in at.text_input if "NIGHTS per city" in t.label][0].set_value("2").run()

btn("Generate Travel Quotation").click().run()
print("after generate : exceptions", [e.value for e in at.exception])

btn("Generate PDF").click().run()
print("after PDF build (draft): downloads", downloads())
at.run()
print("after a plain rerun     : downloads", downloads(), "<- must stay available")

btn("Generate Final Quotation").click().run()
print("after finalize : exceptions", [e.value for e in at.exception],
      "| finalized:", at.session_state["finalized"], "| qno:", at.session_state["quotation_no"])
print("  buttons:", [b.label for b in at.button])
print("  downloads:", downloads())
print("  dashboard 'Total quotations' right after finalize:", [m.value for m in at.metric][:1] or "empty-state", "| info:", [i.value[:40] for i in at.info if "No quotations" in i.value])

if btn("Generate PDF"):
    btn("Generate PDF").click().run()
    print("after PDF build (final): downloads", downloads())

at.run()
print("dashboard after one more rerun:", [m.value for m in at.metric][:1] or "empty-state")
rows = sqlite3.connect(DB_PATH).execute("select quotation_no, customer_name from quotations").fetchall()
print("db rows:", rows)
os.remove(DB_PATH)
