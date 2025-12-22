import sqlite3
import json
from datetime import datetime
import uuid

import numpy as np

def make_json_safe(obj):
    """
    Recursively convert numpy / pandas types to native Python types
    so json.dumps() will work.
    """
    if isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items()}

    if isinstance(obj, list):
        return [make_json_safe(v) for v in obj]

    if isinstance(obj, np.integer):
        return int(obj)

    if isinstance(obj, np.floating):
        return float(obj)

    if hasattr(obj, "item"):
        return obj.item()

    return obj



DB_NAME = "quotations.db"


def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS quotations (
            internal_id INTEGER PRIMARY KEY AUTOINCREMENT,
            quotation_no TEXT UNIQUE,
            customer_name TEXT,
            cities TEXT,
            total_cost REAL,
            created_at TEXT,
            quotation_json TEXT
        )
    """)

    conn.commit()
    conn.close()


def save_quotation(customer_name, cities, total_cost, quotation_data):
    conn = get_connection()
    cur = conn.cursor()

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    safe_data = make_json_safe(quotation_data)

    # Step 1: insert row WITHOUT quotation_no
    cur.execute("""
        INSERT INTO quotations
        (customer_name, cities, total_cost, created_at, quotation_json)
        VALUES (?, ?, ?, ?, ?)
    """, (
        customer_name,
        ", ".join(cities),
        float(total_cost),
        created_at,
        json.dumps(safe_data)
    ))

    # Step 2: get auto-generated internal ID
    internal_id = cur.lastrowid

    # Step 3: generate readable quotation number
    quotation_no = generate_quotation_no(internal_id)

    # Step 4: update row with quotation_no
    cur.execute("""
        UPDATE quotations
        SET quotation_no = ?
        WHERE internal_id = ?
    """, (quotation_no, internal_id))

    conn.commit()
    conn.close()

    return quotation_no




def get_all_quotations():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT quotation_no, customer_name, cities, total_cost, created_at
        FROM quotations
        ORDER BY internal_id DESC
    """)

    rows = cur.fetchall()
    conn.close()
    return rows


def generate_quotation_no(internal_id):
    year = datetime.now().year
    return f"QT-{year}-{internal_id:04d}"

def migrate_schema():
    conn = get_connection()
    cur = conn.cursor()

    # Get existing columns
    cur.execute("PRAGMA table_info(quotations)")
    columns = {row[1] for row in cur.fetchall()}

    # Case 1: very old schema (no internal_id, no quotation_no)
    if "internal_id" not in columns:
        cur.execute("""
            ALTER TABLE quotations RENAME TO quotations_old
        """)

        cur.execute("""
            CREATE TABLE quotations (
                internal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                quotation_no TEXT UNIQUE,
                customer_name TEXT,
                cities TEXT,
                total_cost REAL,
                created_at TEXT,
                quotation_json TEXT
            )
        """)

        # Copy old data
        cur.execute("""
            INSERT INTO quotations (customer_name, cities, total_cost, created_at, quotation_json)
            SELECT customer_name, cities, total_cost, created_at, quotation_json
            FROM quotations_old
        """)

        cur.execute("DROP TABLE quotations_old")

    # Refresh columns after migration
    cur.execute("PRAGMA table_info(quotations)")
    columns = {row[1] for row in cur.fetchall()}

    # Case 2: internal_id exists but quotation_no missing
    if "quotation_no" not in columns:
        cur.execute("ALTER TABLE quotations ADD COLUMN quotation_no TEXT")

    # Backfill quotation_no if missing
    cur.execute("""
        SELECT internal_id FROM quotations WHERE quotation_no IS NULL
    """)
    rows = cur.fetchall()

    for (internal_id,) in rows:
        quotation_no = generate_quotation_no(internal_id)
        cur.execute(
            "UPDATE quotations SET quotation_no = ? WHERE internal_id = ?",
            (quotation_no, internal_id)
        )

    conn.commit()
    conn.close()
