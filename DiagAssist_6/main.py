"""
main.py
--------
Entry point for DiagAssist.

=============================================================================
HYBRID ARCHITECTURE (two runtime modes, one shared pipeline)
=============================================================================

              DiagAssist UI (ui_renderer.py)
                        |
                Runtime Selector (this file)
                        |
          -----------------------------------
          |                                 |
   Google ADK + Gemini                Offline Agent
   (agent_adk.ADKAgentAdapter)       (agent.DiagAssistAgent)
          |                                 |
          -----------------------------------
                        |
                    MCP Tools (mcp/mcp_server.py)
                        |
                  SQLite Database (database/dtc_database.db)

Both agents are driven through the exact same call:

    response = agent.handle_query(query)   # -> {"type": ..., ...} dict
    rendered = render_response(response)   # -> str

agent.py (offline) already returns that dict shape natively. agent_adk.py's
real ADK Agent does not, by default, expose a synchronous handle_query() —
so a small adapter (agent_adk.ADKAgentAdapter) wraps it to match the same
interface. Because both agents are interchangeable from main.py's point of
view, the chat loop, the UI renderer, and the rest of the diagnostic
workflow below are 100% shared between modes — no duplication.

Neither agent.py's nor agent_adk.py's core logic was changed to build this;
agent_adk.py only gained an additive adapter class at the bottom of the
file, and agent.py is untouched.

Usage:
    python main.py
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "ui"))

from agent import DiagAssistAgent  # noqa: E402
from ui_renderer import render_response  # noqa: E402

BANNER = r"""
=================================================
               DiagAssist AI
    Autonomous Automotive Repair Assistant
=================================================
"""

MODE_ADK = "Google ADK + Gemini AI Mode"
MODE_OFFLINE = "Offline Diagnostic Mode"


def print_banner() -> None:
    print(BANNER)


def prompt_mode_choice() -> str:
    """Ask the user to pick a startup mode. Returns "1" or "2"."""
    print("Select Diagnostic Mode:\n")
    print("1. Google ADK + Gemini AI Mode")
    print("2. Offline Diagnostic Mode\n")

    while True:
        choice = input("Enter choice: ").strip()
        if choice in ("1", "2"):
            return choice
        print("Invalid choice. Please enter 1 or 2.")


def init_offline_agent() -> DiagAssistAgent:
    """Build the offline agent. This never depends on any external API,
    so it is also used as the guaranteed fallback target for ADK mode."""
    agent = DiagAssistAgent()
    print("Offline agent initialized successfully.")
    return agent


def try_init_adk_agent():
    """Attempt to start Google ADK + Gemini mode.

    Returns the initialized ADKAgentAdapter on success, or None if it could
    not be started (missing/invalid credentials, quota exceeded, ADK not
    installed, etc.) — in which case a warning has already been printed and
    the caller should fall back to the offline agent.
    """
    print("Starting Google ADK Agent...\n")

    try:
        # Imported lazily so that running in Offline mode never requires
        # google-adk / google-genai to be installed at all.
        import agent_adk
    except Exception as exc:  # noqa: BLE001 - missing optional dependency, etc.
        print("ERROR:")
        print(f"Could not load the Google ADK integration ({exc}).\n")
        print("Switching to Offline Diagnostic Mode...\n")
        return None

    try:
        adapter = agent_adk.create_adk_agent()
        # Lightweight connectivity check: a real round trip to Gemini that
        # surfaces an invalid API key or exhausted quota *now*, at startup,
        # rather than failing unpredictably mid-conversation later.
        adapter.handle_query("ping")
    except agent_adk.GeminiUnavailableError as exc:
        print("ERROR:")
        print(f"Gemini API unavailable or quota exceeded.\n  ({exc})\n")
        print("Switching to Offline Diagnostic Mode...\n")
        return None
    except Exception as exc:  # noqa: BLE001 - belt-and-suspenders catch-all
        print("ERROR:")
        print(f"Unexpected error starting Google ADK Agent ({exc}).\n")
        print("Switching to Offline Diagnostic Mode...\n")
        return None

    print("Google ADK + Gemini agent initialized successfully.")
    print("Gemini connectivity verified.\n")
    return adapter


def main():
    print_banner()
    print("Enter a DTC code (e.g. P0420) or a question about one.")
    print("Type 'quit' or press Ctrl+C to exit.\n")

    choice = prompt_mode_choice()
    print()

    active_mode = MODE_OFFLINE
    agent = None

    if choice == "1":
        adk_agent = try_init_adk_agent()
        if adk_agent is not None:
            agent = adk_agent
            active_mode = MODE_ADK

    if agent is None:
        agent = init_offline_agent()
        active_mode = MODE_OFFLINE

    print(f"\n[Active Mode: {active_mode}]\n")

    while True:
        try:
            query = input(f"({active_mode}) > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not query:
            continue
        if query.lower() in ("quit", "exit"):
            print("Goodbye.")
            break

        try:
            response = agent.handle_query(query)
        except Exception as exc:  # noqa: BLE001
            # Automatic mid-conversation fallback: if the active agent is
            # the ADK/Gemini agent and it fails for any reason (quota
            # exhausted mid-session, transient network error, etc.), switch
            # to the offline agent and re-run the same query so the user
            # still gets an answer this turn instead of a crash.
            if active_mode == MODE_ADK:
                print("\nERROR:")
                print(f"Google ADK Agent failed during the conversation ({exc}).")
                print("Switching to Offline Diagnostic Mode...\n")
                agent = init_offline_agent()
                active_mode = MODE_OFFLINE
                print(f"\n[Active Mode: {active_mode}]\n")
                try:
                    response = agent.handle_query(query)
                except Exception as offline_exc:  # noqa: BLE001
                    print(f"\nOffline agent also failed: {offline_exc}\n")
                    continue
            else:
                print(f"\nUnexpected error handling query: {exc}\n")
                continue

        rendered = render_response(response)
        print("\n" + rendered + "\n")


if __name__ == "__main__":
    main()
