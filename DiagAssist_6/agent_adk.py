"""
agent_adk.py
-------------
DiagAssist agent built on the real Google Agent Development Kit (ADK),
replacing the hand-rolled DiagAssistAgent in agent.py with an actual
google.adk.agents.Agent, and registering lookup_dtc as a proper
google.adk.tools.FunctionTool.

Setup:
    pip install google-adk
    export GOOGLE_API_KEY="your-gemini-api-key"
    # or, for Vertex AI auth instead of an API key:
    # export GOOGLE_GENAI_USE_VERTEXAI=TRUE
    # export GOOGLE_CLOUD_PROJECT="your-project"
    # export GOOGLE_CLOUD_LOCATION="us-central1"

Run:
    python agent_adk.py

This mirrors agent.py's CLI loop, but now an actual Gemini model decides
when to call lookup_dtc (instead of a regex), reads the SKILL.md content
as its system instruction, and produces the natural-language explanation
itself — while the tool call still returns only grounded, database-backed
facts, exactly as required by SKILL.md.
"""

import asyncio
import os

from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.adk.tools import FunctionTool
from google.genai import types

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_PATH = os.path.join(BASE_DIR, "skills", "diagnostic-troubleshooting", "SKILL.md")

# --- Load the existing lookup_dtc function without letting our local
# "mcp" folder shadow the installed "mcp" SDK package (see agent.py for
# the full explanation of why importlib is used here instead of sys.path).
import importlib.util  # noqa: E402

_mcp_server_path = os.path.join(BASE_DIR, "mcp", "mcp_server.py")
_spec = importlib.util.spec_from_file_location("diagassist_mcp_server", _mcp_server_path)
_mcp_server_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mcp_server_module)

lookup_dtc = _mcp_server_module.lookup_dtc


def _load_skill_instruction() -> str:
    """Use the existing SKILL.md content verbatim as the agent's system
    instruction, so behavior stays defined in one place rather than being
    duplicated between SKILL.md and Python code."""
    if not os.path.exists(SKILL_PATH):
        raise FileNotFoundError(f"Skill file not found: {SKILL_PATH}")
    with open(SKILL_PATH, "r", encoding="utf-8") as f:
        return f.read()


def build_agent() -> Agent:
    """Construct the real ADK Agent, with lookup_dtc registered as a
    FunctionTool. ADK auto-generates the tool's parameter schema from
    lookup_dtc's type hints and docstring, so no manual JSON schema is
    needed here."""
    instruction = _load_skill_instruction()

    agent = Agent(
        name="diagassist_agent",
        model="gemini-2.5-flash",
        description=(
            "Diagnostic repair planner that looks up automotive DTC codes "
            "and explains grounded repair steps."
        ),
        instruction=instruction,
        tools=[FunctionTool(lookup_dtc)],
    )
    return agent


async def run_query(runner: InMemoryRunner, user_id: str, session_id: str, query: str) -> str:
    """Send one user message to the agent and collect the final text reply."""
    final_text_parts = []

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=query)]),
    ):
        # ADK streams Events; we only care about the model's final text output.
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    final_text_parts.append(part.text)

    return "".join(final_text_parts).strip()


# ===========================================================================
# Hybrid-mode adapter (added for the two-mode runtime selector in main.py)
# ===========================================================================
#
# Everything above this point is the original, untouched ADK implementation
# (build_agent / run_query / main_async / the `python agent_adk.py` CLI).
#
# main.py needs ONE thing from whichever agent is active: a synchronous
# `handle_query(query: str) -> dict` method that returns the same response
# shape produced by agent.DiagAssistAgent.handle_query():
#
#   {"type": "diagnostic_results", "results": [{"code", "tool_result", ...}]}
#   {"type": "refusal", "message": "..."}
#
# agent.py already returns that shape natively. The real ADK agent does not
# — it streams Events from an async Runner and lets Gemini compose free-form
# text. Rather than rewriting agent_adk.py's core logic (forbidden by the
# brief) or rewriting ui_renderer.py, this adapter class translates between
# the two: it drives the async Runner under the hood, watches the Event
# stream for the lookup_dtc FunctionCall/FunctionResponse pair Gemini
# triggers, and reassembles them into the exact same {"code", "tool_result"}
# dict agent.py would have produced. That keeps the Repair Card rendering,
# severity badges, and checklist UI 100% identical in both modes.
#
# Gemini's own natural-language explanation is preserved too, attached as an
# extra "ai_explanation" key that ui_renderer.py simply ignores (it only
# reads "type"/"results"/"message"), so nothing about the renderer needs to
# change for this to work.
# ===========================================================================

from google.genai import errors as genai_errors  # noqa: E402


class GeminiUnavailableError(RuntimeError):
    """Raised when the Gemini/ADK backend cannot be used right now (missing
    credentials, quota exhausted, network/auth failure, etc.). main.py
    catches this specific exception to trigger the automatic fallback to
    the offline agent, both at startup and mid-conversation."""


def check_environment() -> None:
    """Fail fast, before ever touching the network, if no Gemini credential
    is configured. This produces an immediate, clear error instead of a
    confusing stack trace from deep inside the genai client."""
    has_api_key = bool(os.environ.get("GOOGLE_API_KEY"))
    uses_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true")
    if not (has_api_key or uses_vertex):
        raise GeminiUnavailableError(
            "No Gemini credentials found. Set GOOGLE_API_KEY, or set "
            "GOOGLE_GENAI_USE_VERTEXAI=TRUE with Vertex AI project/location env vars."
        )


class ADKAgentAdapter:
    """Wraps the real Google ADK Agent (build_agent()) so it exposes the same
    synchronous `handle_query(query) -> dict` interface as DiagAssistAgent in
    agent.py. This is the adapter referenced in the architecture diagram —
    it lets main.py, ui_renderer.py, and the rest of the chat loop treat the
    ADK agent and the offline agent completely interchangeably."""

    def __init__(self, user_id: str = "local-user", app_name: str = "diagassist"):
        check_environment()
        try:
            self.agent = build_agent()  # unchanged ADK Agent construction
            self.runner = InMemoryRunner(agent=self.agent, app_name=app_name)
            self.user_id = user_id
            self.session_id = asyncio.run(self._create_session())
        except GeminiUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface any init failure uniformly
            raise GeminiUnavailableError(f"Failed to initialize Google ADK agent: {exc}") from exc

    async def _create_session(self) -> str:
        session = await self.runner.session_service.create_session(
            app_name=self.runner.app_name, user_id=self.user_id,
        )
        return session.id

    def handle_query(self, query: str) -> dict:
        """Synchronous entry point matching DiagAssistAgent.handle_query().
        Internally drives the async ADK Runner to completion."""
        try:
            return asyncio.run(self._handle_query_async(query))
        except GeminiUnavailableError:
            raise
        except (genai_errors.APIError, genai_errors.UnknownApiResponseError) as exc:
            # Covers HTTP 4xx/5xx from Gemini: auth failures, quota
            # exhaustion (429), transient server errors, etc.
            raise GeminiUnavailableError(f"Gemini API error: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - any other runtime failure
            raise GeminiUnavailableError(f"Google ADK agent failed: {exc}") from exc

    async def _handle_query_async(self, query: str) -> dict:
        results = []
        explanation_parts = []
        pending_call_args = {}  # function_call.id -> args, to recover "code"
        # for tool calls whose result has no "code" key (e.g. the error path).

        async for event in self.runner.run_async(
            user_id=self.user_id,
            session_id=self.session_id,
            new_message=types.Content(role="user", parts=[types.Part(text=query)]),
        ):
            for call in event.get_function_calls():
                if call.name == "lookup_dtc":
                    pending_call_args[call.id] = (call.args or {}).get("code", "")

            for resp in event.get_function_responses():
                if resp.name != "lookup_dtc":
                    continue
                tool_result = resp.response or {}
                code = (
                    tool_result.get("code")
                    or pending_call_args.get(resp.id, "")
                ).upper()
                results.append({"code": code, "tool_result": tool_result})

            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        explanation_parts.append(part.text)

        explanation = "".join(explanation_parts).strip()

        if results:
            response = {"type": "diagnostic_results", "results": results}
            if explanation:
                # Extra, additive key — ui_renderer.py ignores unknown keys,
                # so existing rendering is unaffected.
                response["ai_explanation"] = explanation
            return response

        # Gemini didn't call the tool at all (e.g. it judged the question
        # off-topic per SKILL.md) — mirror agent.py's refusal shape.
        return {
            "type": "refusal",
            "message": explanation or (
                "I'm DiagAssist's Gemini-powered mode, but I didn't get a "
                "usable response. Please try rephrasing your question."
            ),
        }


def create_adk_agent() -> "ADKAgentAdapter":
    """Convenience factory used by main.py. Raises GeminiUnavailableError
    (instead of a raw exception) on any failure, so the caller has one
    well-known exception type to catch for the offline fallback."""
    return ADKAgentAdapter()


async def main_async():
    agent = build_agent()
    runner = InMemoryRunner(agent=agent, app_name="diagassist")

    user_id = "local-user"
    session = await runner.session_service.create_session(
        app_name="diagassist",
        user_id=user_id,
    )

    print("DiagAssist (ADK-backed) ready. Type a DTC code or question.")
    print("Requires GOOGLE_API_KEY (or Vertex AI auth) to be set.\n")

    while True:
        try:
            query = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting DiagAssist.")
            break

        if not query:
            continue
        if query.lower() in ("quit", "exit"):
            break

        reply = await run_query(runner, user_id, session.id, query)
        print(reply, "\n")


if __name__ == "__main__":
    asyncio.run(main_async())
