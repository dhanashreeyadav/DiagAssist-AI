"""
streamlit_app.py
==================
DiagAssist AI — Autonomous Automotive Repair Intelligence Platform
Web frontend (Streamlit).

This file is a PRESENTATION LAYER ONLY. It does not contain any diagnostic
logic, regex, scoring, or repair-knowledge of its own. Every fact shown on
screen (DTC description, severity, estimated time, repair steps) comes
straight from a call to one of the two existing, unmodified backend agents:

    agent.DiagAssistAgent          -> Offline Diagnostic Mode
    agent_adk.ADKAgentAdapter       -> Google ADK + Gemini AI Mode

Both expose the same synchronous contract used by main.py (the CLI):

    response = agent.handle_query(query)
    # -> {"type": "diagnostic_results", "results": [...]}
    # -> {"type": "refusal", "message": "..."}

This module never talks to the MCP server, the SQLite database, or Gemini
directly — it only ever calls `agent.handle_query()`. That keeps the whole
existing architecture (MCP tools, DTC database, Google ADK pipeline, offline
reasoning) completely untouched and fully reusable from main.py at the same
time.

A few presentation values shown on the report cards (repair complexity,
recommended technician skill level, and a "components mentioned" list) are
not fields the backend returns. Rather than invent numbers, they are
computed with small, deterministic, clearly-labeled heuristics directly
from the real fields the backend *does* return (severity, repair_steps,
description) — see the "Derived insight helpers" section below. Nothing on
this page is randomly generated or hard-coded mock data.

Run:
    pip install -r requirements.txt
    pip install streamlit reportlab
    streamlit run streamlit_app.py
"""

import html
import io
import json
import os
import re
import sys
import time
from datetime import datetime

import streamlit as st

# ---------------------------------------------------------------------------
# Path setup — identical pattern to main.py, so this file can sit next to
# agent.py / agent_adk.py and import them directly regardless of the
# directory `streamlit run` was launched from.
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from agent import DiagAssistAgent  # noqa: E402  (offline backend, untouched)

DB_PATH = os.path.join(BASE_DIR, "database", "dtc_database.db")

MODE_ADK = "Google ADK + Gemini Mode"
MODE_OFFLINE = "Offline Diagnostic Mode"

NAV_DASHBOARD = "🏠 Dashboard"
NAV_DIAGNOSTIC = "🔍 Diagnostic Center"
NAV_REPORTS = "📄 Repair Reports"
NAV_STATUS = "🖥 System Status"
NAV_ABOUT = "ℹ️ About"
NAV_PAGES = [NAV_DASHBOARD, NAV_DIAGNOSTIC, NAV_REPORTS, NAV_STATUS, NAV_ABOUT]


# =============================================================================
# THEME / CSS
# =============================================================================
# Dark, metallic, electric-blue automotive-dashboard theme. The signature
# motif is the animated "scan sweep" bar — a glowing horizontal line that
# echoes an OBD-II diagnostic scan in progress. It appears under page
# headers and as the centerpiece of the AI-analysis loading sequence; every
# other surface (cards, panels, badges) is kept flat and quiet so that one
# motif stays memorable instead of competing with decoration everywhere.
def inject_theme() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500;600&display=swap');

        :root {
            --bg-primary: #0A0D12;
            --bg-panel: #11151D;
            --bg-card: #161B25;
            --bg-card-hover: #1B2230;
            --border: #232B3A;
            --border-soft: #1C2330;
            --accent: #2F9BFF;
            --accent-glow: #6FD3FF;
            --accent-soft: rgba(47, 155, 255, 0.12);
            --text-primary: #E8ECF2;
            --text-muted: #8C96A8;
            --text-faint: #5C6678;
            --low: #2ECC71;
            --medium: #F5A623;
            --high: #E5484D;
            --critical: #FF2D7A;
        }

        html, body, .stApp {
            background-color: var(--bg-primary) !important;
            color: var(--text-primary);
            font-family: 'Inter', sans-serif;
        }

        section[data-testid="stSidebar"] {
            background-color: var(--bg-panel) !important;
            border-right: 1px solid var(--border);
        }

        h1, h2, h3, h4 {
            font-family: 'Rajdhani', sans-serif !important;
            letter-spacing: 0.02em;
            color: var(--text-primary) !important;
        }

        code, .mono {
            font-family: 'JetBrains Mono', monospace !important;
        }

        /* Hide default Streamlit chrome for a cleaner product feel */
        #MainMenu, footer { visibility: hidden; }

        /* ---- Buttons ---- */
        .stButton > button {
            background: linear-gradient(135deg, var(--accent), #1577D6);
            color: #ffffff;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            letter-spacing: 0.02em;
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        .stButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 6px 18px rgba(47, 155, 255, 0.35);
        }

        /* ---- Hero / scan sweep signature element ---- */
        .scan-bar {
            position: relative;
            height: 3px;
            width: 100%;
            background: var(--border);
            border-radius: 3px;
            overflow: hidden;
            margin: 0.4rem 0 1.4rem 0;
        }
        .scan-bar::after {
            content: '';
            position: absolute;
            top: 0; left: -30%;
            width: 30%; height: 100%;
            background: linear-gradient(90deg, transparent, var(--accent-glow), transparent);
            animation: scanSweep 1.6s linear infinite;
        }
        @keyframes scanSweep {
            0% { left: -30%; }
            100% { left: 130%; }
        }

        /* ---- Generic animated entrance ---- */
        .fade-in {
            animation: fadeInUp 0.45s ease-out both;
        }
        @keyframes fadeInUp {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* ---- Feature / generic cards ---- */
        .feature-card, .diag-card, .insight-panel, .status-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1.1rem 1.2rem;
            margin-bottom: 0.9rem;
        }
        .feature-card {
            transition: border-color 0.15s ease, transform 0.15s ease;
        }
        .feature-card:hover {
            border-color: var(--accent);
            transform: translateY(-2px);
        }
        .feature-card .icon { font-size: 1.7rem; }
        .feature-card h4 { margin: 0.4rem 0 0.3rem 0; }
        .feature-card p { color: var(--text-muted); font-size: 0.92rem; margin: 0; }

        /* ---- Diagnostic report card header ---- */
        .diag-card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-soft);
            padding-bottom: 0.6rem;
            margin-bottom: 0.7rem;
        }
        .diag-code {
            font-family: 'JetBrains Mono', monospace;
            font-size: 1.35rem;
            font-weight: 600;
            color: var(--accent-glow);
        }
        .diag-card h5 {
            font-family: 'Rajdhani', sans-serif;
            color: var(--text-muted);
            text-transform: uppercase;
            font-size: 0.78rem;
            letter-spacing: 0.08em;
            margin: 0.9rem 0 0.4rem 0;
        }

        /* ---- Severity badges ---- */
        .badge {
            display: inline-block;
            padding: 0.22rem 0.7rem;
            border-radius: 999px;
            font-size: 0.8rem;
            font-weight: 600;
            letter-spacing: 0.02em;
        }
        .badge-low { background: rgba(46, 204, 113, 0.14); color: var(--low); border: 1px solid rgba(46,204,113,0.35); }
        .badge-medium { background: rgba(245, 166, 35, 0.14); color: var(--medium); border: 1px solid rgba(245,166,35,0.35); }
        .badge-high { background: rgba(229, 72, 77, 0.14); color: var(--high); border: 1px solid rgba(229,72,77,0.35); }
        .badge-critical { background: rgba(255, 45, 122, 0.16); color: var(--critical); border: 1px solid rgba(255,45,122,0.4); }
        .badge-unknown { background: rgba(140, 150, 168, 0.14); color: var(--text-muted); border: 1px solid var(--border); }

        /* ---- Component chips ---- */
        .chip {
            display: inline-block;
            background: var(--accent-soft);
            color: var(--accent-glow);
            border: 1px solid rgba(47,155,255,0.3);
            border-radius: 6px;
            padding: 0.18rem 0.55rem;
            margin: 0.15rem 0.25rem 0.15rem 0;
            font-size: 0.82rem;
        }

        /* ---- Repair timeline ---- */
        .timeline-step {
            display: flex;
            gap: 0.7rem;
            align-items: flex-start;
            padding: 0.55rem 0;
        }
        .timeline-num {
            flex-shrink: 0;
            width: 28px; height: 28px;
            border-radius: 50%;
            background: var(--accent-soft);
            border: 1px solid var(--accent);
            color: var(--accent-glow);
            display: flex; align-items: center; justify-content: center;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.8rem;
            font-weight: 600;
        }
        .timeline-connector {
            width: 1px;
            flex: 1;
            background: var(--border);
            margin-left: 14px;
        }
        .timeline-text { color: var(--text-primary); font-size: 0.94rem; padding-top: 0.2rem; }

        /* ---- Status pills (sidebar / system status) ---- */
        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.35rem 0.7rem;
            border-radius: 8px;
            font-size: 0.85rem;
            font-weight: 600;
            background: var(--bg-card);
            border: 1px solid var(--border);
        }
        .pill-good { color: var(--low); border-color: rgba(46,204,113,0.35); }
        .pill-warn { color: var(--medium); border-color: rgba(245,166,35,0.35); }
        .pill-bad { color: var(--high); border-color: rgba(229,72,77,0.35); }

        .text-muted { color: var(--text-muted); }
        .text-faint { color: var(--text-faint); font-size: 0.82rem; }

        /* ---- Architecture diagram (System Status page) ---- */
        .arch-box {
            border: 1px solid var(--border);
            background: var(--bg-card);
            border-radius: 10px;
            padding: 0.6rem 1rem;
            text-align: center;
            font-family: 'Rajdhani', sans-serif;
            font-weight: 600;
            color: var(--text-primary);
        }
        .arch-box.active { border-color: var(--accent); box-shadow: 0 0 14px rgba(47,155,255,0.25); color: var(--accent-glow); }
        .arch-line { width: 1px; height: 22px; background: var(--border); margin: 0 auto; }
        .arch-row { display: flex; gap: 1rem; }
        .arch-row > div { flex: 1; }

        /* ---- Mobile responsiveness ---- */
        @media (max-width: 640px) {
            .feature-card, .diag-card, .insight-panel { padding: 0.85rem; }
            .diag-code { font-size: 1.1rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# SESSION STATE
# =============================================================================
def init_session_state() -> None:
    defaults = {
        "requested_mode": None,        # mode last successfully (or attemptedly) applied
        "agent": None,                  # the live agent instance (offline or ADK adapter)
        "agent_mode": None,             # MODE_ADK or MODE_OFFLINE — the mode actually ACTIVE
        "adk_error": None,              # last ADK init/connectivity error, if any
        "fallback_notice": None,        # banner text shown after an auto-fallback
        "history": [],                  # session diagnostic history (list of dicts)
        "current_report": None,         # most recent agent response dict
        "current_query": "",
        "current_mode_used": None,
        "last_diagnostic_time": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# =============================================================================
# AGENT MANAGEMENT  (the only section that talks to the backend agents)
# =============================================================================
def init_offline_agent() -> DiagAssistAgent:
    """Build the offline agent. No external dependency, always succeeds."""
    return DiagAssistAgent()


def try_init_adk_agent():
    """Attempt to start Google ADK + Gemini mode.

    Returns (adapter, error_message). adapter is None on failure, in which
    case error_message explains why (missing credentials, quota exceeded,
    google-adk not installed, etc.) — mirroring main.py's CLI fallback path.
    """
    try:
        import agent_adk  # imported lazily so Offline mode never needs it
    except Exception as exc:  # noqa: BLE001
        return None, f"Could not load the Google ADK integration: {exc}"

    try:
        adapter = agent_adk.create_adk_agent()
        # Lightweight live round trip to Gemini, run once at connect time so
        # an invalid key / exhausted quota is caught now, not mid-session.
        adapter.handle_query("ping")
    except Exception as exc:  # noqa: BLE001 — agent_adk.GeminiUnavailableError or anything else
        return None, str(exc)

    return adapter, None


def ensure_agent(selected_mode: str) -> None:
    """Make sure the active agent matches `selected_mode`, with automatic,
    silent fallback to Offline mode if ADK mode can't be reached. Cheap to
    call on every page render — it only does real work when the requested
    mode actually changes."""
    if st.session_state.requested_mode == selected_mode and st.session_state.agent is not None:
        return

    st.session_state.requested_mode = selected_mode
    st.session_state.fallback_notice = None
    st.session_state.adk_error = None

    if selected_mode == MODE_ADK:
        with st.spinner("Connecting to Google ADK + Gemini..."):
            adapter, err = try_init_adk_agent()
        if adapter is not None:
            st.session_state.agent = adapter
            st.session_state.agent_mode = MODE_ADK
            return
        st.session_state.adk_error = err
        st.session_state.fallback_notice = (
            f"⚠️ Gemini API unavailable or quota exceeded ({err}). "
            f"Automatically switched to Offline Diagnostic Mode."
        )

    # Either Offline was explicitly chosen, or ADK failed above and we fall
    # back here — both land on the always-available offline agent.
    st.session_state.agent = init_offline_agent()
    st.session_state.agent_mode = MODE_OFFLINE


def run_diagnosis(query: str) -> dict:
    """Call the active agent, with automatic mid-conversation fallback to
    Offline mode if the ADK agent fails on this specific query (e.g. quota
    exhausted between calls). Returns the response dict and records which
    mode actually produced it in st.session_state.current_mode_used."""
    status = st.status("Running diagnostic agent...", expanded=True)
    with status:
        st.write("🛰️ AI Agent analyzing vehicle data...")
        time.sleep(0.35)
        st.write("📚 Consulting diagnostic knowledge base...")
        time.sleep(0.3)
        st.write("🧠 Generating repair strategy...")

        mode_used = st.session_state.agent_mode
        try:
            response = st.session_state.agent.handle_query(query)
            status.update(label="Diagnosis complete", state="complete")
        except Exception as exc:  # noqa: BLE001
            if st.session_state.agent_mode == MODE_ADK:
                st.write(f"⚠️ Gemini call failed ({exc}). Switching to Offline Diagnostic Mode...")
                st.session_state.agent = init_offline_agent()
                st.session_state.agent_mode = MODE_OFFLINE
                st.session_state.requested_mode = MODE_OFFLINE
                st.session_state.fallback_notice = (
                    f"⚠️ Google ADK Agent failed mid-session ({exc}). "
                    f"Switched to Offline Diagnostic Mode."
                )
                mode_used = MODE_OFFLINE
                try:
                    response = st.session_state.agent.handle_query(query)
                    status.update(label="Diagnosis complete (Offline fallback)", state="complete")
                except Exception as exc2:  # noqa: BLE001
                    status.update(label="Diagnosis failed", state="error")
                    response = {"type": "refusal", "message": f"Offline agent also failed: {exc2}"}
            else:
                status.update(label="Diagnosis failed", state="error")
                response = {"type": "refusal", "message": f"Unexpected error: {exc}"}

    st.session_state.current_mode_used = mode_used
    return response


# =============================================================================
# DERIVED INSIGHT HELPERS
# -----------------------------------------------------------------------------
# Everything below reads ONLY fields the backend already returns (severity,
# description, repair_steps). Nothing here calls an LLM, invents a part
# number, or fabricates a statistic — these are small deterministic
# functions that re-present real diagnostic text, clearly labeled as such.
# =============================================================================
SEVERITY_STYLES = {
    "low": ("🟢", "Low", "badge-low"),
    "medium": ("🟡", "Medium", "badge-medium"),
    "high": ("🔴", "High", "badge-high"),
    "critical": ("🚨", "Critical", "badge-critical"),
}

# Common automotive component terms. Used only to detect which components
# the backend's own description/repair_steps text already mentions — a
# literal keyword scan over real returned text, not a generated parts list.
COMPONENT_TERMS = [
    ("oxygen sensor", "Oxygen Sensor"), ("o2 sensor", "O2 Sensor"),
    ("catalytic converter", "Catalytic Converter"), ("spark plug", "Spark Plugs"),
    ("ignition coil", "Ignition Coil"), ("fuel injector", "Fuel Injector"),
    ("fuel pump", "Fuel Pump"), ("fuel pressure", "Fuel Pressure Regulator"),
    ("mass airflow", "Mass Airflow (MAF) Sensor"), ("maf sensor", "MAF Sensor"),
    ("thermostat", "Thermostat"), ("fuel cap", "Fuel Cap"),
    ("evap hose", "EVAP Hose"), ("purge valve", "EVAP Purge Valve"),
    ("vacuum", "Vacuum Lines"), ("intake manifold", "Intake Manifold"),
    ("coolant temperature sensor", "Coolant Temperature Sensor"),
    ("coolant", "Coolant System"), ("exhaust", "Exhaust System"),
    ("battery", "Battery"), ("alternator", "Alternator"),
    ("crankshaft position sensor", "Crankshaft Position Sensor"),
    ("camshaft position sensor", "Camshaft Position Sensor"),
    ("throttle body", "Throttle Body"), ("egr valve", "EGR Valve"),
    ("knock sensor", "Knock Sensor"), ("wiring harness", "Wiring Harness"),
    ("wheel speed sensor", "Wheel Speed Sensor"), ("brake", "Brake System"),
    ("transmission", "Transmission"), ("turbocharger", "Turbocharger"),
    ("radiator", "Radiator"), ("water pump", "Water Pump"),
    ("timing belt", "Timing Belt"), ("timing chain", "Timing Chain"),
]

CAUSE_CUE_RE = re.compile(
    r"(?:often due to|usually caused by|commonly caused by|typically due to|"
    r"due to|caused by)\s+(.*?)(?:\.|$)",
    re.IGNORECASE,
)


def severity_badge_html(severity: str) -> str:
    key = (severity or "").strip().lower()
    emoji, label, css_class = SEVERITY_STYLES.get(key, ("⚪", severity or "Unknown", "badge-unknown"))
    return f'<span class="badge {css_class}">{emoji} {html.escape(label)}</span>'


def extract_possible_causes(description: str) -> list:
    """Parse the cue-phrase clause (e.g. 'often due to X, Y, or Z') out of
    the real DTC description text into a short bullet list."""
    if not description:
        return []
    match = CAUSE_CUE_RE.search(description)
    if not match:
        return []
    clause = match.group(1)
    parts = re.split(r",\s*(?:or\s+)?|\s+or\s+|\s+and\s+", clause)
    return [p.strip().rstrip(".") for p in parts if p.strip()]


def extract_mentioned_components(text: str) -> list:
    """Literal keyword scan for known automotive component terms that
    already appear in the backend's own description/repair-step text."""
    text_l = (text or "").lower()
    found, seen = [], set()
    for keyword, display_name in COMPONENT_TERMS:
        if keyword in text_l and display_name not in seen:
            found.append(display_name)
            seen.add(display_name)
    return found


def estimate_complexity(severity: str, repair_steps: list) -> tuple:
    """Deterministic, clearly-labeled estimate (not a backend field) of
    repair complexity and recommended technician level, derived from the
    real severity and the real number of repair steps returned."""
    sev = (severity or "").strip().lower()
    n_steps = len(repair_steps or [])
    if sev == "high" or n_steps >= 5:
        return "High", "Certified / Master Technician"
    if sev == "medium" or n_steps >= 3:
        return "Medium", "Certified Technician"
    return "Low", "Entry-Level Technician"


# =============================================================================
# PDF / EXPORT
# =============================================================================
def build_pdf_report(query: str, mode_used: str, response: dict) -> bytes:
    """Render the current diagnostic response into a downloadable PDF using
    reportlab. Pure presentation of already-returned data."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem, Table, TableStyle,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.7 * inch, bottomMargin=0.7 * inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleX", parent=styles["Title"], textColor=colors.HexColor("#11151D"))
    h2_style = ParagraphStyle("H2X", parent=styles["Heading2"], textColor=colors.HexColor("#1577D6"))
    body_style = ParagraphStyle("BodyX", parent=styles["BodyText"], leading=15)

    story = [
        Paragraph("DiagAssist AI — Diagnostic Report", title_style),
        Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", body_style),
        Paragraph(f"Diagnostic Engine: {mode_used}", body_style),
        Paragraph(f"Query: {html.escape(query)}", body_style),
        Spacer(1, 0.25 * inch),
    ]

    if response.get("type") == "refusal":
        story.append(Paragraph(html.escape(response.get("message", ""))), )
    else:
        for result in response.get("results", []):
            code = result.get("code", "—")
            tool_result = result.get("tool_result", {})
            story.append(Paragraph(f"DTC Code: {code}", h2_style))

            if "error" in tool_result:
                story.append(Paragraph(html.escape(tool_result["error"]), body_style))
                story.append(Spacer(1, 0.2 * inch))
                continue

            severity = tool_result.get("severity", "Unknown")
            est_time = tool_result.get("estimated_time", "Unknown")
            description = tool_result.get("description", "")
            steps = tool_result.get("repair_steps", [])
            causes = extract_possible_causes(description)
            components = extract_mentioned_components(description + " " + " ".join(steps))
            complexity, skill = estimate_complexity(severity, steps)

            table = Table(
                [["Severity", severity], ["Estimated Repair Time", est_time],
                 ["Estimated Complexity", complexity], ["Recommended Skill Level", skill]],
                colWidths=[2.2 * inch, 3.5 * inch],
            )
            table.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1577D6")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(table)
            story.append(Spacer(1, 0.15 * inch))

            story.append(Paragraph("Fault Explanation", h2_style))
            story.append(Paragraph(html.escape(description), body_style))

            if causes:
                story.append(Paragraph("Possible Causes", h2_style))
                story.append(ListFlowable(
                    [ListItem(Paragraph(html.escape(c), body_style)) for c in causes], bulletType="bullet",
                ))

            if components:
                story.append(Paragraph("Components Involved", h2_style))
                story.append(Paragraph(html.escape(", ".join(components)), body_style))

            if steps:
                story.append(Paragraph("Repair Workflow", h2_style))
                story.append(ListFlowable(
                    [ListItem(Paragraph(html.escape(s), body_style)) for s in steps], bulletType="1",
                ))

            parts_estimate = result.get("parts_estimate")
            if parts_estimate and parts_estimate.get("likely_parts"):
                story.append(Paragraph("Likely Parts Needed", h2_style))
                story.append(ListFlowable(
                    [ListItem(Paragraph(html.escape(p), body_style)) for p in parts_estimate["likely_parts"]],
                    bulletType="bullet",
                ))

            story.append(Spacer(1, 0.3 * inch))

        ai_explanation = response.get("ai_explanation")
        if ai_explanation:
            story.append(Paragraph("Gemini AI Explanation", h2_style))
            story.append(Paragraph(html.escape(ai_explanation), body_style))

    doc.build(story)
    return buffer.getvalue()


# =============================================================================
# UI: SIDEBAR
# =============================================================================
def render_sidebar() -> str:
    with st.sidebar:
        st.markdown("## 🚗 DiagAssist")
        st.caption("Autonomous Automotive Repair Intelligence Platform")
        st.markdown("---")

        page = st.radio("Navigation", NAV_PAGES, label_visibility="collapsed")

        st.markdown("---")
        st.markdown("**Runtime Mode**")
        selected_mode = st.radio(
            "Diagnostic engine",
            [MODE_ADK, MODE_OFFLINE],
            label_visibility="collapsed",
        )
        ensure_agent(selected_mode)

        if st.session_state.agent_mode == MODE_ADK:
            st.markdown('<div class="status-pill pill-good">🟢 ADK Connected</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="status-pill pill-warn">🟡 Offline Mode Active</div>', unsafe_allow_html=True)

        if st.session_state.fallback_notice:
            st.warning(st.session_state.fallback_notice)

        st.markdown("---")
        if st.button("🧹 Clear Session", use_container_width=True):
            st.session_state.history = []
            st.session_state.current_report = None
            st.session_state.current_query = ""
            st.rerun()

        st.markdown(
            '<p class="text-faint">Google ADK + Gemini AI · MCP Tools · SQLite DTC Database</p>',
            unsafe_allow_html=True,
        )

    return page


# =============================================================================
# UI: DASHBOARD
# =============================================================================
def render_dashboard() -> None:
    st.markdown("# 🚗 DiagAssist AI")
    st.markdown("##### Intelligent Automotive Diagnostic Assistant")
    st.markdown('<div class="scan-bar"></div>', unsafe_allow_html=True)

    cards = [
        ("🔧", "DTC Fault Diagnosis", "Analyze OBD-II trouble codes and identify root causes."),
        ("🧠", "AI Repair Planning", "Generate repair workflows using Google ADK + Gemini AI."),
        ("📡", "Offline Reliability", "Continue diagnostics even without cloud AI access."),
        ("📊", "Parts & Repair Insights", "Estimate required components and repair complexity."),
    ]
    cols = st.columns(2)
    for i, (icon, title, desc) in enumerate(cards):
        with cols[i % 2]:
            st.markdown(
                f"""
                <div class="feature-card fade-in" style="animation-delay:{i * 0.07}s">
                    <div class="icon">{icon}</div>
                    <h4>{html.escape(title)}</h4>
                    <p>{html.escape(desc)}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    c1.metric("Active Engine", "Gemini ADK" if st.session_state.agent_mode == MODE_ADK else "Offline")
    c2.metric("Diagnostics This Session", len(st.session_state.history))
    last_time = st.session_state.last_diagnostic_time
    c3.metric("Last Diagnostic", last_time.strftime("%H:%M:%S") if last_time else "—")

    st.info("Use **🔍 Diagnostic Center** in the sidebar to run a new vehicle diagnosis.")


# =============================================================================
# UI: DIAGNOSTIC CENTER
# =============================================================================
def render_diagnostic_center() -> None:
    st.markdown("# 🔍 Diagnostic Center")
    st.markdown('<div class="scan-bar"></div>', unsafe_allow_html=True)

    query = st.text_area(
        "Enter DTC code or describe vehicle problem",
        placeholder="e.g. P0420, P0300, or \"Engine light is ON and the vehicle shakes\"",
        height=90,
    )
    st.caption("Examples: `P0420` · `P0300` · \"Engine light is ON and the vehicle shakes\"")

    if st.button("🔎 Start AI Diagnosis", type="primary", use_container_width=True):
        if not query.strip():
            st.warning("Please enter a DTC code or describe the problem.")
        else:
            response = run_diagnosis(query)
            st.session_state.current_report = response
            st.session_state.current_query = query
            st.session_state.last_diagnostic_time = datetime.now()
            st.session_state.history.append({
                "timestamp": st.session_state.last_diagnostic_time,
                "query": query,
                "mode": st.session_state.current_mode_used,
                "response": response,
            })
            st.rerun()

    if st.session_state.current_report:
        st.markdown("---")
        render_diagnostic_report(
            st.session_state.current_report,
            st.session_state.current_query,
            st.session_state.current_mode_used,
        )


def render_diagnostic_report(response: dict, query: str, mode_used: str) -> None:
    """Renders the full report UI: summary, root cause, timeline, parts &
    cost panel, and AI agent insights — for every DTC result in `response`."""
    if response.get("type") == "refusal":
        st.markdown(
            f'<div class="diag-card fade-in">ℹ️ {html.escape(response.get("message", ""))}</div>',
            unsafe_allow_html=True,
        )
        return

    for result in response.get("results", []):
        code = result.get("code", "—")
        tool_result = result.get("tool_result", {})

        if "error" in tool_result:
            st.markdown(
                f"""
                <div class="diag-card fade-in">
                    <div class="diag-card-header">
                        <span class="diag-code">{html.escape(code)}</span>
                        <span class="badge badge-unknown">⚠️ NOT FOUND</span>
                    </div>
                    <p class="text-muted">{html.escape(tool_result["error"])}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            continue

        severity = tool_result.get("severity", "Unknown")
        est_time = tool_result.get("estimated_time", "Unknown")
        description = tool_result.get("description", "")
        steps = tool_result.get("repair_steps", [])
        causes = extract_possible_causes(description)
        components = extract_mentioned_components(description + " " + " ".join(steps))
        complexity, skill = estimate_complexity(severity, steps)
        parts_estimate = result.get("parts_estimate")

        # ---- Vehicle Diagnostic Summary -----------------------------------
        st.markdown(
            f"""
            <div class="diag-card fade-in">
                <div class="diag-card-header">
                    <span class="diag-code">{html.escape(code)}</span>
                    {severity_badge_html(severity)}
                </div>
                <p class="text-muted">⏱ Estimated Repair Time: <strong>{html.escape(est_time)}</strong></p>
            """,
            unsafe_allow_html=True,
        )

        # ---- Root Cause Analysis -------------------------------------------
        st.markdown('<h5>Root Cause Analysis</h5>', unsafe_allow_html=True)
        st.markdown(f'<p>{html.escape(description)}</p>', unsafe_allow_html=True)
        if causes:
            st.markdown(
                "".join(f'<span class="chip">{html.escape(c)}</span>' for c in causes),
                unsafe_allow_html=True,
            )
        if components:
            st.markdown('<h5>Component Impact</h5>', unsafe_allow_html=True)
            st.markdown(
                "".join(f'<span class="chip">🔧 {html.escape(c)}</span>' for c in components),
                unsafe_allow_html=True,
            )

        st.markdown("</div>", unsafe_allow_html=True)

        # ---- Repair Workflow Timeline --------------------------------------
        with st.container():
            st.markdown('<div class="diag-card fade-in"><h5>Repair Workflow Timeline</h5>', unsafe_allow_html=True)
            for i, step in enumerate(steps):
                is_last = i == len(steps) - 1
                st.markdown(
                    f"""
                    <div class="timeline-step">
                        <div>
                            <div class="timeline-num">{i + 1}</div>
                            {'' if is_last else '<div class="timeline-connector"></div>'}
                        </div>
                        <div class="timeline-text">{html.escape(step)}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            st.markdown("</div>", unsafe_allow_html=True)

        # ---- Parts & Cost Panel + AI Agent Insights (side by side) --------
        col_parts, col_insights = st.columns(2)
        with col_parts:
            st.markdown('<div class="diag-card fade-in"><h5>Parts &amp; Cost Panel</h5>', unsafe_allow_html=True)
            if parts_estimate and parts_estimate.get("likely_parts"):
                st.markdown('<p class="text-muted">Live estimate from the Parts Agent (A2A):</p>', unsafe_allow_html=True)
                for part in parts_estimate["likely_parts"]:
                    st.markdown(f'<span class="chip">🔧 {html.escape(part)}</span>', unsafe_allow_html=True)
            elif components:
                st.markdown(
                    '<p class="text-muted">No live Parts Agent estimate available. '
                    'Components referenced in the repair steps:</p>',
                    unsafe_allow_html=True,
                )
                for c in components:
                    st.markdown(f'<span class="chip">🔧 {html.escape(c)}</span>', unsafe_allow_html=True)
            else:
                st.markdown('<p class="text-muted">No parts data available for this fault.</p>', unsafe_allow_html=True)

            st.markdown(
                f"""
                <p class="text-faint">Estimated Repair Time: <strong>{html.escape(est_time)}</strong></p>
                <p class="text-faint">Repair Complexity (estimated): <strong>{complexity}</strong></p>
                <p class="text-faint">Recommended Skill Level (estimated): <strong>{skill}</strong></p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with col_insights:
            agent_label = "🤖 Google ADK Agent (Gemini)" if mode_used == MODE_ADK else "⚙️ Offline Diagnostic Engine"
            st.markdown(
                f"""
                <div class="diag-card fade-in"><h5>AI Agent Insights</h5>
                <p class="text-muted">Agent Used:</p>
                <p><strong>{agent_label}</strong></p>
                <p class="text-muted">Knowledge Source:</p>
                <p><strong>📂 Automotive DTC Database</strong></p>
                <p class="text-muted">Reasoning Status:</p>
                <p><strong>✅ Diagnosis Completed</strong></p>
                </div>
                """,
                unsafe_allow_html=True,
            )

    ai_explanation = response.get("ai_explanation")
    if ai_explanation:
        st.markdown(
            f"""
            <div class="diag-card fade-in">
                <h5>Gemini AI Explanation</h5>
                <p>{html.escape(ai_explanation)}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ---- Export controls ---------------------------------------------------
    col_a, col_b = st.columns(2)
    with col_a:
        try:
            pdf_bytes = build_pdf_report(query, mode_used, response)
            st.download_button(
                "📄 Download PDF Report", data=pdf_bytes,
                file_name=f"diagassist_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                mime="application/pdf", use_container_width=True,
            )
        except Exception as exc:  # noqa: BLE001
            st.caption(f"PDF export unavailable: {exc}")
    with col_b:
        export_payload = {"query": query, "mode": mode_used, "response": response}
        st.download_button(
            "📤 Export as JSON", data=json.dumps(export_payload, indent=2, default=str),
            file_name=f"diagassist_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json", use_container_width=True,
        )


# =============================================================================
# UI: REPAIR REPORTS (session history)
# =============================================================================
def render_repair_reports() -> None:
    st.markdown("# 📄 Repair Reports")
    st.markdown('<div class="scan-bar"></div>', unsafe_allow_html=True)

    if not st.session_state.history:
        st.info("No diagnostics run yet this session. Visit **🔍 Diagnostic Center** to get started.")
        return

    col1, col2 = st.columns([3, 1])
    with col1:
        st.caption(f"{len(st.session_state.history)} diagnostic session(s) recorded this session.")
    with col2:
        if st.button("🧹 Clear History", use_container_width=True):
            st.session_state.history = []
            st.rerun()

    for i, entry in enumerate(reversed(st.session_state.history)):
        idx = len(st.session_state.history) - i
        ts = entry["timestamp"].strftime("%Y-%m-%d %H:%M:%S") if entry["timestamp"] else "—"
        with st.expander(f"#{idx} · {entry['query'][:60]} · {ts} · {entry['mode']}"):
            render_diagnostic_report(entry["response"], entry["query"], entry["mode"])


# =============================================================================
# UI: SYSTEM STATUS
# =============================================================================
def render_system_status() -> None:
    st.markdown("# 🖥 System Status")
    st.markdown('<div class="scan-bar"></div>', unsafe_allow_html=True)

    adk_active = st.session_state.agent_mode == MODE_ADK
    db_ok = os.path.exists(DB_PATH)
    has_credentials = bool(os.environ.get("GOOGLE_API_KEY")) or os.environ.get(
        "GOOGLE_GENAI_USE_VERTEXAI", ""
    ).lower() in ("1", "true")

    st.markdown('<div class="arch-row">', unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            f'<div class="status-card"><p class="text-muted">Active Agent</p>'
            f'<h4>{"🤖 Google ADK + Gemini" if adk_active else "⚙️ Offline Engine"}</h4></div>',
            unsafe_allow_html=True,
        )
    with col2:
        pill = "pill-good" if has_credentials else "pill-warn"
        label = "🟢 Credentials Found" if has_credentials else "🟡 No Gemini Credentials"
        st.markdown(
            f'<div class="status-card"><p class="text-muted">API Connection Status</p>'
            f'<div class="status-pill {pill}">{label}</div></div>',
            unsafe_allow_html=True,
        )
    with col3:
        pill = "pill-good" if db_ok else "pill-bad"
        label = "🟢 Connected" if db_ok else "🔴 Not Found"
        st.markdown(
            f'<div class="status-card"><p class="text-muted">Database Availability</p>'
            f'<div class="status-pill {pill}">{label}</div></div>',
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    last_time = st.session_state.last_diagnostic_time
    st.markdown(
        f'<p class="text-muted">Last Diagnostic Time: '
        f'<strong>{last_time.strftime("%Y-%m-%d %H:%M:%S") if last_time else "No diagnostics run yet"}</strong></p>',
        unsafe_allow_html=True,
    )
    if st.session_state.adk_error:
        st.caption(f"Last Google ADK error: {st.session_state.adk_error}")

    st.markdown("### Architecture")
    adk_class = "arch-box active" if adk_active else "arch-box"
    offline_class = "arch-box" if adk_active else "arch-box active"
    st.markdown(
        f"""
        <div style="display:flex; flex-direction:column; align-items:center; gap:0;">
            <div class="arch-box">👤 User</div>
            <div class="arch-line"></div>
            <div class="arch-box">🖥 Web UI (streamlit_app.py)</div>
            <div class="arch-line"></div>
            <div class="arch-box">🧭 Runtime Manager</div>
            <div class="arch-line"></div>
            <div style="display:flex; gap:2rem;">
                <div style="display:flex; flex-direction:column; align-items:center;">
                    <div class="{adk_class}">🤖 Google ADK<br/>+ Gemini</div>
                </div>
                <div style="display:flex; flex-direction:column; align-items:center;">
                    <div class="{offline_class}">⚙️ Offline Agent</div>
                </div>
            </div>
            <div class="arch-line"></div>
            <div class="arch-box">🔌 MCP Diagnostic Tools</div>
            <div class="arch-line"></div>
            <div class="arch-box">🗄 SQLite DTC Database</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# UI: ABOUT
# =============================================================================
def render_about() -> None:
    st.markdown("# ℹ️ About DiagAssist AI")
    st.markdown('<div class="scan-bar"></div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="diag-card fade-in">
        <p><strong>DiagAssist AI</strong> is an autonomous automotive repair intelligence
        platform with two interchangeable diagnostic engines behind one shared interface:</p>
        <ul>
            <li><strong>Google ADK + Gemini AI Mode</strong> — a real
            <code>google.adk.agents.Agent</code> with <code>lookup_dtc</code> registered as a
            FunctionTool, letting Gemini decide when to call the diagnostic tool and explain
            results in natural language.</li>
            <li><strong>Offline Diagnostic Mode</strong> — a regex/logic-based agent that
            reaches the same MCP tool and SQLite-backed DTC database with no external
            dependency, and is the automatic fallback target whenever Gemini is unavailable.</li>
        </ul>
        <p>Both engines share the same MCP tool layer (<code>mcp/mcp_server.py</code>) and the
        same SQLite database (<code>database/dtc_database.db</code>), so a diagnosis is
        equally grounded regardless of which engine answered it.</p>
        <p class="text-muted">This Streamlit application is a frontend layer only — it
        contains no diagnostic logic of its own and calls the existing agents exactly as
        the CLI (<code>main.py</code>) does.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# MAIN
# =============================================================================
def main() -> None:
    st.set_page_config(
        page_title="DiagAssist AI",
        page_icon="🚗",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    init_session_state()
    inject_theme()

    page = render_sidebar()

    if st.session_state.fallback_notice and page != NAV_STATUS:
        st.warning(st.session_state.fallback_notice)

    if page == NAV_DASHBOARD:
        render_dashboard()
    elif page == NAV_DIAGNOSTIC:
        render_diagnostic_center()
    elif page == NAV_REPORTS:
        render_repair_reports()
    elif page == NAV_STATUS:
        render_system_status()
    elif page == NAV_ABOUT:
        render_about()


if __name__ == "__main__":
    main()
