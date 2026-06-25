"""
agent.py
---------
A lightweight ADK-style agent for DiagAssist.

Responsibilities:
  - Register the diagnostic-troubleshooting Agent Skill (its instructions,
    loaded from SKILL.md).
  - Connect to the MCP server and expose its tools (lookup_dtc) to itself.
  - Receive a raw user query (text).
  - Decide whether the query needs the lookup_dtc tool (by extracting DTC
    codes with a regex, exactly as instructed in SKILL.md).
  - Execute the tool call(s) against the MCP server.
  - Format a final structured response, ready to hand to ui_renderer.py.
  - Maintain working memory within a session (so follow-up questions like
    "how long will that take?" resolve against the most recently discussed
    DTC) and long-term memory across sessions (a persisted JSONL history of
    past diagnostic lookups).

This file does not depend on any specific cloud LLM provider — the
"reasoning" steps that don't require real natural-language generation
(code extraction, refusal logic, error handling) are implemented directly
in Python so the whole pipeline can run fully offline. The hand-off point
to an LLM (e.g. for paraphrasing the description) is clearly marked.
"""

import json
import os
import re
import sys
import time
import uuid

# Allow importing the MCP server module directly for local/offline execution.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# NOTE: We deliberately load mcp_server.py via importlib (by file path) rather
# than adding its directory to sys.path. Our local folder is named "mcp",
# which would otherwise shadow the installed third-party "mcp" SDK package
# that mcp_server.py itself depends on (from mcp.server.fastmcp import ...).
import importlib.util  # noqa: E402

_mcp_server_path = os.path.join(BASE_DIR, "mcp", "mcp_server.py")
_spec = importlib.util.spec_from_file_location("diagassist_mcp_server", _mcp_server_path)
_mcp_server_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mcp_server_module)

lookup_dtc = _mcp_server_module.lookup_dtc

# Day 4 (Agent Quality): structured logging, tracing, and metrics.
# Loaded via importlib (same pattern as mcp_server above) so this file
# never needs to add BASE_DIR to sys.path.
_observability_path = os.path.join(BASE_DIR, "observability.py")
_obs_spec = importlib.util.spec_from_file_location("diagassist_observability", _observability_path)
_observability_module = importlib.util.module_from_spec(_obs_spec)
_obs_spec.loader.exec_module(_observability_module)

_obs_logger = _observability_module.get_logger()

# Day 5 (Prototype to Production): A2A client used to call the independent
# Parts Agent. Loaded the same way to avoid sys.path collisions.
_a2a_client_path = os.path.join(BASE_DIR, "a2a", "a2a_client.py")
_a2a_spec = importlib.util.spec_from_file_location("diagassist_a2a_client", _a2a_client_path)
_a2a_client_module = importlib.util.module_from_spec(_a2a_spec)
_a2a_spec.loader.exec_module(_a2a_client_module)

is_parts_agent_available = _a2a_client_module.is_parts_agent_available
request_parts_estimate = _a2a_client_module.request_parts_estimate

SKILL_PATH = os.path.join(BASE_DIR, "skills", "diagnostic-troubleshooting", "SKILL.md")
DTC_PATTERN = re.compile(r"\b[PBCU]\d{4}\b", re.IGNORECASE)

# Long-term memory: a simple append-only JSONL log of every diagnostic
# lookup, persisted across process restarts. Each line is one JSON record.
MEMORY_DIR = os.path.join(BASE_DIR, "memory")
HISTORY_PATH = os.path.join(MEMORY_DIR, "history.jsonl")

# Phrases that indicate the user is asking a follow-up about the *previous*
# result rather than introducing a new request. Used only when no DTC code
# is present in the current message.
FOLLOWUP_KEYWORDS = (
    "how long", "how serious", "severity", "what about that",
    "is that bad", "is it bad", "what else", "anything else",
    "more detail", "more details", "explain that", "what does that mean",
)


class SessionMemory:
    """Working memory for a single conversation: keeps the most recent
    diagnostic results so follow-up questions can resolve without the user
    repeating the DTC code."""

    def __init__(self, max_items: int = 5):
        self.session_id = str(uuid.uuid4())
        self.max_items = max_items
        self.recent_results = []  # list of {"code": ..., "tool_result": ...}

    def remember(self, code: str, tool_result: dict) -> None:
        self.recent_results.append({"code": code, "tool_result": tool_result})
        self.recent_results = self.recent_results[-self.max_items :]

    def last_result(self):
        return self.recent_results[-1] if self.recent_results else None

    def all_results(self):
        return list(self.recent_results)


def _ensure_memory_dir() -> None:
    os.makedirs(MEMORY_DIR, exist_ok=True)


def _append_long_term_memory(session_id: str, code: str, tool_result: dict) -> None:
    """Append one record to the persisted long-term history log."""
    _ensure_memory_dir()
    record = {
        "timestamp": time.time(),
        "session_id": session_id,
        "code": code,
        "tool_result": tool_result,
    }
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def load_long_term_memory(limit: int = 50) -> list:
    """Read back the most recent long-term memory records (across all past
    sessions/process runs). Useful for a 'show my past diagnostic sessions'
    feature or for debugging."""
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]
    return lines[-limit:]


class DiagAssistAgent:
    """Minimal ADK-style agent wired to a single Agent Skill + MCP tool,
    with session-scoped working memory and persisted long-term memory."""

    def __init__(self, persist_memory: bool = True):
        self.skill_instructions = self._load_skill()
        self.tools = {"lookup_dtc": lookup_dtc}
        self.session = SessionMemory()
        self.persist_memory = persist_memory

    def _load_skill(self) -> str:
        """Load the SKILL.md content so the agent's behavior is documented
        and (in a full LLM-backed deployment) injected into the system prompt."""
        if not os.path.exists(SKILL_PATH):
            raise FileNotFoundError(f"Skill file not found: {SKILL_PATH}")
        with open(SKILL_PATH, "r", encoding="utf-8") as f:
            return f.read()

    def _extract_codes(self, query: str) -> list:
        """Find all DTC-like substrings in the user query."""
        return sorted(set(match.upper() for match in DTC_PATTERN.findall(query)))

    def _is_diagnostic_request(self, query: str, codes: list) -> bool:
        """A query is in-scope if it contains a DTC code, or explicitly
        mentions diagnostic/repair vocabulary, or is a follow-up about a
        previous result still held in working memory."""
        if codes:
            return True
        if self._is_followup(query):
            return True
        keywords = ("dtc", "code", "diagnos", "repair", "fault", "check engine")
        return any(kw in query.lower() for kw in keywords)

    def _is_followup(self, query: str) -> bool:
        """A message with no DTC code is treated as a follow-up about the
        last discussed code only if it both matches a follow-up phrase AND
        working memory actually has something to follow up on."""
        if not self.session.last_result():
            return False
        return any(kw in query.lower() for kw in FOLLOWUP_KEYWORDS)

    def handle_query(self, query: str) -> dict:
        """
        Main entry point. Returns a structured response dict:
        {
            "type": "diagnostic_results" | "refusal",
            "results": [ ... ],   # only for diagnostic_results
            "message": "..."      # only for refusal
            "followup": True      # present only when resolved via memory
        }

        Every call is wrapped in a trace (Day 4 - Agent Quality) that records
        each decision step with timing, and every lookup_dtc call is logged
        individually with success/failure and latency.
        """
        with _obs_logger.trace_query(query) as trace:
            codes = self._extract_codes(query)
            trace.step("extract_codes", codes=codes)

            if not self._is_diagnostic_request(query, codes):
                trace.step("route_decision", route="refusal_off_topic")
                trace.set_outcome("refusal")
                return {
                    "type": "refusal",
                    "message": (
                        "I'm DiagAssist, a focused diagnostic repair planner. "
                        "I can only help with vehicle Diagnostic Trouble Codes (DTCs), "
                        "like P0420 or P0300. Please share a DTC code or a question "
                        "about one, and I'll pull up the repair plan."
                    ),
                }

            # Follow-up: no new code given, but working memory has a recent
            # result and the phrasing matches a follow-up pattern.
            if not codes and self._is_followup(query):
                trace.step("route_decision", route="followup_from_memory")
                last = self.session.last_result()
                trace.set_outcome("diagnostic_results")
                return {
                    "type": "diagnostic_results",
                    "results": [last],
                    "followup": True,
                }

            if not codes:
                trace.step("route_decision", route="refusal_no_code_found")
                trace.set_outcome("refusal")
                return {
                    "type": "refusal",
                    "message": (
                        "I can see this is about a vehicle issue, but I couldn't find a "
                        "DTC code in your message. Could you provide the exact code "
                        "(e.g. P0420) from your scan tool?"
                    ),
                }

            trace.step("route_decision", route="tool_call", codes=codes)

            results = []
            for code in codes:
                call_start = time.time()
                tool_result = self.tools["lookup_dtc"](code)
                latency_ms = (time.time() - call_start) * 1000

                success = "error" not in tool_result
                _obs_logger.log_tool_call(
                    code=code,
                    success=success,
                    latency_ms=latency_ms,
                    error=tool_result.get("error") if not success else None,
                )
                trace.step(
                    "tool_call_complete",
                    code=code,
                    success=success,
                    latency_ms=round(latency_ms, 3),
                )

                results.append({"code": code, "tool_result": tool_result})

                # Day 5 (A2A Protocol): if the lookup succeeded, ask the
                # independent Parts Agent for a likely-parts estimate based
                # on the grounded repair steps. This is a real cross-process
                # call to a separate agent, not a local function call — if
                # the Parts Agent isn't running, we degrade gracefully and
                # simply omit the parts estimate rather than failing the
                # whole diagnostic response.
                if success and is_parts_agent_available():
                    parts_response = request_parts_estimate(
                        dtc_code=code,
                        repair_steps=tool_result.get("repair_steps", []),
                    )
                    trace.step(
                        "a2a_parts_agent_call",
                        code=code,
                        success="error" not in parts_response,
                    )
                    if "error" not in parts_response:
                        results[-1]["parts_estimate"] = parts_response

                # Working memory: remember this result for follow-up questions.
                self.session.remember(code, tool_result)

                # Long-term memory: persist every lookup across process runs.
                if self.persist_memory:
                    _append_long_term_memory(self.session.session_id, code, tool_result)

            trace.set_outcome("diagnostic_results")
            return {"type": "diagnostic_results", "results": results}


def main():
    """Simple CLI loop for local testing."""
    agent = DiagAssistAgent()
    print("DiagAssist Agent ready. Type a DTC code or question (Ctrl+C to exit).\n")
    print(f"Session ID: {agent.session.session_id}\n")

    while True:
        try:
            query = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting DiagAssist.")
            break

        if not query:
            continue

        response = agent.handle_query(query)
        print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()

