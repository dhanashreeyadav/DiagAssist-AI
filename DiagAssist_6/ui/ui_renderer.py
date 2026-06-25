"""
ui_renderer.py
---------------
A2UI-style rendering layer for DiagAssist.

Takes the structured agent response (see agent.py) and renders it as:
  - A Card component (one per DTC)
  - A Status Badge (color-coded by severity)
  - A Checklist component (one line per repair step)

This implementation renders to clean, readable plain text / Markdown for
terminal and chat-based front ends. The same data structures could be fed
into a JSON-based A2UI schema for a web or mobile renderer by swapping out
the `render_*` functions below — the data shaping logic stays the same.
"""

SEVERITY_BADGES = {
    "low": "🟢 LOW",
    "medium": "🟡 MEDIUM",
    "high": "🔴 HIGH",
}


def render_status_badge(severity: str) -> str:
    """Render a color-coded status badge for a given severity string."""
    return SEVERITY_BADGES.get(severity.strip().lower(), f"⚪ {severity.upper()}")


def render_checklist(steps: list) -> str:
    """Render a list of repair steps as a checklist."""
    lines = [f"  ✓ {step}" for step in steps]
    return "\n".join(lines)


def render_card(code: str, result: dict) -> str:
    """Render a single Repair Card for one DTC lookup result.

    `result` is the full per-code result dict from agent.py, e.g.:
    {"code": ..., "tool_result": {...}, "parts_estimate": {...} (optional)}
    """
    tool_result = result.get("tool_result", {})

    if "error" in tool_result:
        return (
            f"┌─ Repair Card: {code} ───────────────────────────\n"
            f"│ Status: ⚠️  NOT FOUND\n"
            f"│ {tool_result['error']}\n"
            f"└───────────────────────────────────────────────────"
        )

    description = tool_result.get("description", "")
    severity = tool_result.get("severity", "Unknown")
    estimated_time = tool_result.get("estimated_time", "Unknown")
    repair_steps = tool_result.get("repair_steps", [])
    parts_estimate = result.get("parts_estimate")

    badge = render_status_badge(severity)
    checklist = render_checklist(repair_steps)

    card = (
        f"┌─ Repair Card: {code} ───────────────────────────\n"
        f"│ Severity:     {badge}\n"
        f"│ Repair Time:  {estimated_time}\n"
        f"│\n"
        f"│ Description:\n"
        f"│   {description}\n"
        f"│\n"
        f"│ Checklist:\n"
    )

    # Indent checklist lines under the card body.
    indented_checklist = "\n".join(f"│ {line}" for line in checklist.split("\n"))
    card += indented_checklist + "\n"

    if parts_estimate and parts_estimate.get("likely_parts"):
        card += "│\n│ Likely Parts Needed (via Parts Agent / A2A):\n"
        for part in parts_estimate["likely_parts"]:
            card += f"│   • {part}\n"

    card += "└───────────────────────────────────────────────────"

    return card


def render_response(agent_response: dict) -> str:
    """
    Render a full agent response (as produced by DiagAssistAgent.handle_query)
    into final user-facing text.
    """
    if agent_response["type"] == "refusal":
        return agent_response["message"]

    cards = []
    for result in agent_response.get("results", []):
        cards.append(render_card(result["code"], result))

    return "\n\n".join(cards)


if __name__ == "__main__":
    # Quick manual smoke test using a sample successful and failed result.
    sample_success = {
        "type": "diagnostic_results",
        "results": [
            {
                "code": "P0420",
                "tool_result": {
                    "code": "P0420",
                    "description": "Catalyst System Efficiency Below Threshold (Bank 1).",
                    "severity": "Medium",
                    "estimated_time": "2 Hours",
                    "repair_steps": [
                        "Inspect catalytic converter",
                        "Check O2 sensor",
                        "Verify exhaust leaks",
                    ],
                },
            }
        ],
    }

    sample_refusal = {
        "type": "refusal",
        "message": "I'm DiagAssist, a focused diagnostic repair planner.",
    }

    print(render_response(sample_success))
    print()
    print(render_response(sample_refusal))
