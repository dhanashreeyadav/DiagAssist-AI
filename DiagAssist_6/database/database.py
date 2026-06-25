"""
database.py
------------
Builds a local SQLite database (dtc_database.db) from the mock dataset
in dtc_data.json. Run this once before starting the MCP server.

Usage:
    python database.py
"""

import json
import os
import sqlite3

# Resolve paths relative to this file so the script works from any directory.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(BASE_DIR, "dtc_data.json")
DB_PATH = os.path.join(BASE_DIR, "dtc_database.db")


def create_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Create (or open) the SQLite database connection."""
    conn = sqlite3.connect(db_path)
    return conn


def create_table(conn: sqlite3.Connection) -> None:
    """Create the dtc table if it does not already exist."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dtc (
            code TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            severity TEXT NOT NULL,
            estimated_time TEXT NOT NULL,
            repair_steps TEXT NOT NULL  -- stored as JSON-encoded list
        )
        """
    )
    conn.commit()


def load_json_data(json_path: str = JSON_PATH) -> list:
    """Load the mock DTC dataset from disk."""
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Could not find dataset at {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list) or len(data) == 0:
        raise ValueError("dtc_data.json must contain a non-empty list of records")

    return data


def insert_records(conn: sqlite3.Connection, records: list) -> int:
    """Insert (or replace) all DTC records into the database. Returns count inserted."""
    cursor = conn.cursor()
    count = 0

    for record in records:
        required_keys = {"code", "description", "severity", "estimated_time", "repair_steps"}
        missing = required_keys - record.keys()
        if missing:
            raise ValueError(f"Record {record.get('code', '?')} missing fields: {missing}")

        cursor.execute(
            """
            INSERT OR REPLACE INTO dtc (code, description, severity, estimated_time, repair_steps)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                record["code"],
                record["description"],
                record["severity"],
                record["estimated_time"],
                json.dumps(record["repair_steps"]),
            ),
        )
        count += 1

    conn.commit()
    return count


def verify_table_schema(conn: sqlite3.Connection) -> bool:
    """Sanity check the dtc table exists and has the expected columns."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(dtc)")
    columns = {row[1] for row in cursor.fetchall()}
    expected = {"code", "description", "severity", "estimated_time", "repair_steps"}
    return expected.issubset(columns)


def build_database() -> None:
    """Full pipeline: create db, create table, load json, insert records."""
    print(f"[database.py] Building database at: {DB_PATH}")

    conn = create_connection()
    try:
        create_table(conn)

        if not verify_table_schema(conn):
            raise RuntimeError("dtc table schema verification failed after creation")

        records = load_json_data()
        inserted = insert_records(conn, records)

        print(f"[database.py] Inserted/updated {inserted} DTC records.")
        print("[database.py] Database build complete.")
    finally:
        conn.close()


if __name__ == "__main__":
    build_database()
