"""
mcp_server.py
--------------
MCP Server exposing a single tool, `lookup_dtc`, which queries the local
SQLite database built by database.py and returns structured repair
information for a given automotive Diagnostic Trouble Code (DTC).

Installation:
    pip install mcp

Run:
    python mcp_server.py

This server communicates over stdio, which is the standard transport
expected by most MCP-compatible agent frameworks (including ADK-style
agents that spawn the server as a subprocess).
"""

import json
import os
import re
import sqlite3

from mcp.server.fastmcp import FastMCP

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(os.path.dirname(BASE_DIR), "database", "dtc_database.db")

# Basic OBD-II DTC pattern: one letter (P/B/C/U) followed by 4 digits.
DTC_PATTERN = re.compile(r"^[PBCU]\d{4}$", re.IGNORECASE)

mcp = FastMCP("diagassist-mcp")


def _get_connection() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(
            f"Database not found at {DB_PATH}. Run database.py first to build it."
        )
    return sqlite3.connect(DB_PATH)


@mcp.tool()
def lookup_dtc(code: str) -> dict:
    """
    Look up repair information for an automotive Diagnostic Trouble Code (DTC).

    Args:
        code: A DTC string such as "P0420". Case-insensitive.

    Returns:
        A dictionary with keys: description, severity, estimated_time,
        repair_steps. If the code is invalid or not found, returns a
        dictionary with an "error" key explaining why, and no fabricated
        repair data.
    """
    if not code or not isinstance(code, str):
        return {"error": "No DTC code provided."}

    normalized = code.strip().upper()

    if not DTC_PATTERN.match(normalized):
        return {
            "error": (
                f"'{code}' does not look like a valid DTC. "
                "Expected format: one letter (P/B/C/U) followed by 4 digits, e.g. P0420."
            )
        }

    try:
        conn = _get_connection()
    except FileNotFoundError as exc:
        return {"error": str(exc)}

    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT description, severity, estimated_time, repair_steps "
            "FROM dtc WHERE code = ?",
            (normalized,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    if row is None:
        return {"error": f"DTC '{normalized}' was not found in the database."}

    description, severity, estimated_time, repair_steps_json = row

    return {
        "code": normalized,
        "description": description,
        "severity": severity,
        "estimated_time": estimated_time,
        "repair_steps": json.loads(repair_steps_json),
    }


if __name__ == "__main__":
    # Runs the MCP server over stdio transport.
    mcp.run()
