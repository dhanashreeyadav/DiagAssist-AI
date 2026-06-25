"""
a2a_client.py
--------------
Day 5 (Prototype to Production) - A2A Protocol demonstration, client side.

A small client the Diagnosis Agent (agent.py) uses to call the independent
Parts Agent (parts_agent_server.py) over HTTP, following the same
discover-then-call pattern A2A describes:
  1. Fetch the Agent Card to confirm the agent is reachable and supports
     the skill we need.
  2. Send a task message and get back a structured task result.

This keeps the two agents genuinely independent: the Diagnosis Agent has
no Python-level dependency on the Parts Agent's implementation, only on
its HTTP contract. The Parts Agent could be rewritten in a different
language or replaced with a different implementation entirely without
the Diagnosis Agent's code changing at all.
"""

import httpx

PARTS_AGENT_BASE_URL = "http://127.0.0.1:8001"
PARTS_AGENT_TIMEOUT_SECONDS = 5.0


def is_parts_agent_available() -> bool:
    """Check the Parts Agent's Agent Card to confirm it's reachable before
    attempting a task call. Used so the Diagnosis Agent can degrade
    gracefully (skip the parts estimate) if the Parts Agent isn't running."""
    try:
        response = httpx.get(
            f"{PARTS_AGENT_BASE_URL}/.well-known/agent.json",
            timeout=PARTS_AGENT_TIMEOUT_SECONDS,
        )
        return response.status_code == 200
    except httpx.RequestError:
        return False


def request_parts_estimate(dtc_code: str, repair_steps: list) -> dict:
    """
    Call the Parts Agent's estimate_parts task over HTTP.

    Returns the Parts Agent's structured response dict, or a dict with an
    "error" key if the Parts Agent could not be reached — mirroring how
    lookup_dtc handles its own failure cases, so callers handle both the
    same way (check for an "error" key, never assume success).
    """
    try:
        response = httpx.post(
            f"{PARTS_AGENT_BASE_URL}/tasks/estimate_parts",
            json={"dtc_code": dtc_code, "repair_steps": repair_steps},
            timeout=PARTS_AGENT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except httpx.RequestError as exc:
        return {"error": f"Parts Agent unreachable: {exc}"}
    except httpx.HTTPStatusError as exc:
        return {"error": f"Parts Agent returned an error: {exc.response.status_code}"}
