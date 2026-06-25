"""
judge.py
---------
Day 4 (Agent Quality) - Evaluation half: a "judge" that scores whether a
DiagAssist response is faithfully grounded in the raw lookup_dtc tool
output, with no fabricated or altered facts.

This is intentionally a DETERMINISTIC judge, not an LLM-as-Judge, because
the specific claim DiagAssist needs to defend ("every fact comes verbatim
from the tool, nothing is hallucinated") is checkable by exact comparison
against the tool's JSON — that's a more reliable test than asking another
model to "check for hallucination," and it requires no API key.

Once a real LLM-backed reasoning layer is added (see agent_adk.py), this
deterministic judge should be paired with an LLM-as-Judge for the things
exact comparison CAN'T check: whether the natural-language explanation is
clear, well-organized, and an appropriate tone for a service technician.
That second judge is sketched at the bottom of this file as
`llm_judge_prompt()` — it returns the prompt text to send to a model; it
does not call one itself, since that requires the Gemini API key.

Usage:
    python judge.py
"""

import importlib.util
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_agent_path = os.path.join(BASE_DIR, "agent.py")
_spec = importlib.util.spec_from_file_location("diagassist_agent_for_judge", _agent_path)
_agent_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_agent_module)
DiagAssistAgent = _agent_module.DiagAssistAgent

_ui_path = os.path.join(BASE_DIR, "ui", "ui_renderer.py")
_ui_spec = importlib.util.spec_from_file_location("diagassist_ui_for_judge", _ui_path)
_ui_module = importlib.util.module_from_spec(_ui_spec)
_ui_spec.loader.exec_module(_ui_module)
render_response = _ui_module.render_response


class GroundingJudgeResult:
    def __init__(self, code: str, passed: bool, issues: list):
        self.code = code
        self.passed = passed
        self.issues = issues

    def __repr__(self):
        status = "GROUNDED" if self.passed else "VIOLATION"
        return f"[{status}] {self.code}: {self.issues if self.issues else 'no issues'}"


def judge_grounding(code: str, tool_result: dict, rendered_text: str) -> GroundingJudgeResult:
    """
    Check that every fact present in the rendered output for one DTC also
    appears, verbatim, in the raw tool_result it was supposed to come from.

    This catches the failure modes that matter most for DiagAssist:
      - A severity/time/step that doesn't match the tool's data at all
        (the strongest signal of fabrication).
      - A repair step that appears in the rendered text but was never in
        tool_result["repair_steps"] (an invented step).

    It deliberately does NOT penalize the renderer for paraphrasing the
    `description` field, since some natural-language rewording there is
    expected and acceptable — only the structured facts (severity, time,
    repair steps) need to match exactly, since those are the actionable
    , safety-relevant parts of the response.
    """
    issues = []

    if "error" in tool_result:
        if tool_result["error"] not in rendered_text:
            issues.append("Error message from tool was not faithfully reproduced.")
        return GroundingJudgeResult(code, len(issues) == 0, issues)

    severity = tool_result.get("severity", "")
    estimated_time = tool_result.get("estimated_time", "")
    repair_steps = tool_result.get("repair_steps", [])

    if severity and severity.upper() not in rendered_text.upper():
        issues.append(f"Severity '{severity}' not found verbatim in rendered output.")

    if estimated_time and estimated_time not in rendered_text:
        issues.append(f"Estimated time '{estimated_time}' not found verbatim in rendered output.")

    for step in repair_steps:
        if step not in rendered_text:
            issues.append(f"Repair step missing or altered: '{step}'")

    return GroundingJudgeResult(code, len(issues) == 0, issues)


def run_grounding_eval(test_codes: list) -> list:
    """Run the grounding judge across a list of DTCs (valid and invalid),
    by actually executing them through the real agent + renderer, then
    checking the rendered output against the raw tool data."""
    agent = DiagAssistAgent(persist_memory=False)
    results = []

    for code in test_codes:
        response = agent.handle_query(code)
        rendered_text = render_response(response)

        # There's exactly one result per single-code query here.
        tool_result = response["results"][0]["tool_result"]
        judgement = judge_grounding(code, tool_result, rendered_text)
        results.append(judgement)

    return results


def llm_judge_prompt(query: str, tool_result: dict, rendered_text: str) -> str:
    """
    NOT executed automatically (requires a Gemini API key to actually run).

    Returns the prompt text you would send to an LLM-as-Judge to evaluate
    the *qualitative* aspects the deterministic judge above cannot check:
    clarity, tone, and appropriateness for a service technician audience.

    To wire this up later:
        from google import genai
        client = genai.Client()
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=llm_judge_prompt(query, tool_result, rendered_text),
        )
        print(response.text)
    """
    return f"""You are evaluating an automotive diagnostic assistant's response.

User query: {query!r}

Raw grounded data the assistant had access to:
{tool_result}

Assistant's rendered response:
{rendered_text}

Score the response from 1-5 on each of the following, and give a one-sentence
justification for each score:
1. Clarity — is the explanation easy for a technician to act on quickly?
2. Tone — is it professional and appropriate for a shop-floor tool?
3. Completeness — does it surface all the actionable information (severity,
   time, steps) without burying it in unnecessary text?

Do NOT score factual grounding — that is checked separately by a
deterministic judge. Focus only on clarity, tone, and completeness."""


if __name__ == "__main__":
    test_codes = ["P0420", "P0300", "P0171", "P9999"]
    judgements = run_grounding_eval(test_codes)

    print("=" * 60)
    print("DiagAssist Grounding Judge Report")
    print("=" * 60)
    for j in judgements:
        print(j)

    passed = sum(1 for j in judgements if j.passed)
    print("-" * 60)
    print(f"Result: {passed}/{len(judgements)} responses fully grounded")
    print("=" * 60)
