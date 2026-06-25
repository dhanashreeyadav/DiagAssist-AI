"""
evals.py
---------
Evaluation-Driven Development harness for DiagAssist.

Runs a set of automated test cases against the DiagAssistAgent to verify:
  - Valid DTC codes trigger the lookup_dtc tool and return correct data.
  - Natural-language questions containing a DTC trigger the tool.
  - Off-topic requests are politely refused (no tool call).
  - Invalid/unknown DTC codes return a clear "not found" result.
  - Multiple DTCs in one message are all processed.

Usage:
    python evals.py
"""

import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

# Load agent.py by file path (not via sys.path) to avoid our project's local
# "mcp" folder shadowing the installed third-party "mcp" SDK package.
import importlib.util  # noqa: E402

_agent_path = os.path.join(PROJECT_ROOT, "agent.py")
_spec = importlib.util.spec_from_file_location("diagassist_agent", _agent_path)
_agent_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_agent_module)

DiagAssistAgent = _agent_module.DiagAssistAgent


class EvalResult:
    def __init__(self, name: str, passed: bool, details: str = ""):
        self.name = name
        self.passed = passed
        self.details = details


def test_valid_dtc_direct_code(agent: DiagAssistAgent) -> EvalResult:
    """Test 1: A bare DTC code should trigger the MCP tool and succeed."""
    response = agent.handle_query("P0420")
    passed = (
        response["type"] == "diagnostic_results"
        and len(response["results"]) == 1
        and response["results"][0]["code"] == "P0420"
        and "error" not in response["results"][0]["tool_result"]
    )
    return EvalResult("valid_dtc_direct_code", passed, str(response))


def test_natural_language_question(agent: DiagAssistAgent) -> EvalResult:
    """Test 2: A natural-language question containing a DTC should trigger the tool."""
    response = agent.handle_query("What is P0300?")
    passed = (
        response["type"] == "diagnostic_results"
        and any(r["code"] == "P0300" for r in response["results"])
        and "error" not in response["results"][0]["tool_result"]
    )
    return EvalResult("natural_language_question", passed, str(response))


def test_off_topic_refusal(agent: DiagAssistAgent) -> EvalResult:
    """Test 3: An off-topic request should be politely refused, no tool call."""
    response = agent.handle_query("Tell me a joke")
    passed = response["type"] == "refusal"
    return EvalResult("off_topic_refusal", passed, str(response))


def test_invalid_dtc_not_found(agent: DiagAssistAgent) -> EvalResult:
    """Test 4: A well-formed but unknown DTC should return a 'not found' error."""
    response = agent.handle_query("P9999")
    passed = (
        response["type"] == "diagnostic_results"
        and len(response["results"]) == 1
        and "error" in response["results"][0]["tool_result"]
    )
    return EvalResult("invalid_dtc_not_found", passed, str(response))


def test_multiple_dtcs_processed(agent: DiagAssistAgent) -> EvalResult:
    """Test 5: Multiple DTCs in one message should all be looked up."""
    response = agent.handle_query("I have codes P0420 and P0171, what's going on?")
    codes_found = {r["code"] for r in response.get("results", [])}
    passed = (
        response["type"] == "diagnostic_results"
        and codes_found == {"P0420", "P0171"}
        and all("error" not in r["tool_result"] for r in response["results"])
    )
    return EvalResult("multiple_dtcs_processed", passed, str(response))


def test_malformed_code_handled(agent: DiagAssistAgent) -> EvalResult:
    """Bonus Test 6: A malformed code-like string with diagnostic keywords should
    be treated as a diagnostic request but yield no extractable code, triggering
    a clarification refusal rather than a guess."""
    response = agent.handle_query("My check engine light is on, fault code P42")
    passed = response["type"] == "refusal"
    return EvalResult("malformed_code_handled", passed, str(response))


def test_followup_uses_working_memory(agent: DiagAssistAgent) -> EvalResult:
    """Bonus Test 7 (Day 3 - Sessions & Memory): a follow-up question with no
    DTC code should resolve against the most recently discussed code held in
    working memory, instead of being refused or guessed."""
    first = agent.handle_query("P0420")
    followup = agent.handle_query("how serious is that?")

    passed = (
        first["type"] == "diagnostic_results"
        and followup["type"] == "diagnostic_results"
        and followup.get("followup") is True
        and followup["results"][0]["code"] == "P0420"
    )
    return EvalResult("followup_uses_working_memory", passed, str(followup))


def run_all_tests() -> list:
    agent = DiagAssistAgent()
    tests = [
        test_valid_dtc_direct_code,
        test_natural_language_question,
        test_off_topic_refusal,
        test_invalid_dtc_not_found,
        test_multiple_dtcs_processed,
        test_malformed_code_handled,
        test_followup_uses_working_memory,
    ]

    results = []
    for test_fn in tests:
        try:
            result = test_fn(agent)
        except Exception as exc:  # noqa: BLE001
            result = EvalResult(test_fn.__name__, False, f"Exception raised: {exc}")
        results.append(result)

    return results


def print_report(results: list) -> None:
    passed_count = sum(1 for r in results if r.passed)
    total = len(results)

    print("=" * 60)
    print("DiagAssist Evaluation Report")
    print("=" * 60)

    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"[{status}] {r.name}")
        if not r.passed:
            print(f"        details: {r.details}")

    print("-" * 60)
    print(f"Result: {passed_count}/{total} tests passed")
    print("=" * 60)


if __name__ == "__main__":
    report = run_all_tests()
    print_report(report)

    if not all(r.passed for r in report):
        sys.exit(1)
