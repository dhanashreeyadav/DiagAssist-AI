"""
parts_agent_server.py
-----------------------
Day 5 (Prototype to Production) - A2A Protocol demonstration.

This is a SEPARATE, independent agent from DiagAssistAgent: the Parts
Agent. It has its own process, its own concern (estimating likely
replacement parts from a list of repair steps), and is discoverable and
callable over HTTP exactly the way the A2A Protocol describes:

  1. An Agent Card at a well-known URL describes what this agent can do.
  2. A task endpoint accepts a structured message and returns a structured
     result.

NOTE ON SDK VERSIONING: the official `a2a-sdk` package (v1.1.0 at the time
this was written) implements its AgentCard and message types as protobuf
messages, which is a substantially different and more complex surface than
the pydantic-based API shown in most A2A tutorials. To give you something
you can actually run and test today, this file implements the SAME core
A2A pattern (Agent Card discovery + task-based message passing between
independent agents) using plain FastAPI/httpx instead of fighting that
SDK's current API. It is a protocol-faithful illustration, not a
claim of strict a2a-sdk compliance. Swapping this for the official SDK
later is a matter of replacing the FastAPI routes below with the SDK's
AgentExecutor / A2A server wiring — the agent logic itself doesn't change.

Run:
    pip install fastapi uvicorn httpx
    python a2a/parts_agent_server.py
    # Server listens on http://127.0.0.1:8001
"""

import re
from typing import List

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="DiagAssist Parts Agent")

# A small rule-based mapping from keywords in a repair step to a likely
# replacement part. This stands in for what would otherwise be a parts
# catalog lookup or an LLM call in a production system.
PART_KEYWORD_MAP = {
    "catalytic converter": "Catalytic Converter Assembly",
    "o2 sensor": "Oxygen (O2) Sensor",
    "oxygen sensor": "Oxygen (O2) Sensor",
    "spark plug": "Spark Plug Set",
    "ignition coil": "Ignition Coil",
    "fuel injector": "Fuel Injector",
    "fuel pressure": "Fuel Pump / Fuel Pressure Regulator",
    "thermostat": "Engine Coolant Thermostat",
    "maf sensor": "Mass Air Flow (MAF) Sensor",
    "mass airflow": "Mass Air Flow (MAF) Sensor",
    "iat sensor": "Intake Air Temperature (IAT) Sensor",
    "fuel cap": "Fuel Cap",
    "evap": "EVAP Purge Valve / Hose Kit",
    "purge valve": "EVAP Purge Valve",
    "egr valve": "EGR Valve",
    "throttle body": "Throttle Body Cleaning Kit",
    "idle air control": "Idle Air Control Valve",
}


class PartsEstimateRequest(BaseModel):
    """The 'task message' sent from the Diagnosis Agent to the Parts Agent."""
    dtc_code: str
    repair_steps: List[str]


class PartsEstimateResponse(BaseModel):
    """The 'task result' returned by the Parts Agent."""
    dtc_code: str
    likely_parts: List[str]
    note: str


@app.get("/.well-known/agent.json")
def agent_card():
    """A2A-style Agent Card: describes this agent's identity and
    capabilities so another agent (or a human) can discover what it does
    before calling it."""
    return {
        "name": "diagassist-parts-agent",
        "description": (
            "Estimates likely replacement parts needed for a given set of "
            "automotive repair steps. Independent from the Diagnosis Agent; "
            "called via A2A-style task messages."
        ),
        "version": "1.0.0",
        "skills": [
            {
                "id": "estimate_parts",
                "description": "Given DTC repair steps, estimate likely replacement parts.",
                "input_schema": "PartsEstimateRequest",
                "output_schema": "PartsEstimateResponse",
            }
        ],
        "endpoints": {
            "estimate_parts": "/tasks/estimate_parts",
        },
    }


@app.post("/tasks/estimate_parts", response_model=PartsEstimateResponse)
def estimate_parts(request: PartsEstimateRequest) -> PartsEstimateResponse:
    """The task endpoint. Receives repair steps from another agent process
    and returns a structured parts estimate — this is the actual A2A
    message exchange, two independent agents communicating over HTTP."""
    found_parts = set()

    combined_text = " ".join(request.repair_steps).lower()
    for keyword, part_name in PART_KEYWORD_MAP.items():
        if keyword in combined_text:
            found_parts.add(part_name)

    if not found_parts:
        note = "No specific parts could be confidently inferred from these repair steps."
    else:
        note = (
            "Parts inferred from repair step keywords. This is an estimate, "
            "not a confirmed parts order — verify against the vehicle's "
            "actual condition before ordering."
        )

    return PartsEstimateResponse(
        dtc_code=request.dtc_code,
        likely_parts=sorted(found_parts),
        note=note,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
