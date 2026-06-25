"""
observability.py
------------------
Day 4 (Agent Quality) support module for DiagAssist.

Implements the three observability pillars from the course material:
  - Logs   : structured, timestamped JSON-lines records of individual events
             (e.g. each lookup_dtc call) — "the diary".
  - Traces : one record per user query showing the full step-by-step chain
             (extract codes -> decide route -> call tool -> respond), with
             per-step timing — "the narrative".
  - Metrics: aggregate stats computed from the logs (success rate, refusal
             rate, average latency, most-queried codes) — "the health report".

All data is written to local JSONL files under logs/, so no external
observability backend (Cloud Trace, Datadog, etc.) is required to use this.
The structure is intentionally compatible with that kind of backend later:
each trace/log record is a flat JSON object that could be forwarded as-is.

Usage:
    from observability import get_logger
    logger = get_logger()
    logger.log_tool_call(code="P0420", success=True, latency_ms=4.2)

    with logger.trace_query(query="P0420") as trace:
        trace.step("extract_codes", codes=["P0420"])
        ...
"""

import json
import os
import time
import uuid
from collections import Counter
from contextlib import contextmanager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
TOOL_LOG_PATH = os.path.join(LOGS_DIR, "tool_calls.jsonl")
TRACE_LOG_PATH = os.path.join(LOGS_DIR, "traces.jsonl")


def _ensure_logs_dir() -> None:
    os.makedirs(LOGS_DIR, exist_ok=True)


def _append_jsonl(path: str, record: dict) -> None:
    _ensure_logs_dir()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


class QueryTrace:
    """One trace per user query. Records a sequence of timed steps showing
    exactly how the agent handled that query, from input to final response."""

    def __init__(self, query: str):
        self.trace_id = str(uuid.uuid4())
        self.query = query
        self.start_time = time.time()
        self.steps = []
        self._last_step_time = self.start_time

    def step(self, name: str, **details) -> None:
        """Record one step in the trace, with the time elapsed since the
        previous step (or since the trace started, for the first step)."""
        now = time.time()
        self.steps.append(
            {
                "step": name,
                "elapsed_ms": round((now - self._last_step_time) * 1000, 3),
                "details": details,
            }
        )
        self._last_step_time = now

    def finish(self, outcome: str) -> dict:
        """Finalize the trace and write it to disk. Returns the full record."""
        total_ms = round((time.time() - self.start_time) * 1000, 3)
        record = {
            "trace_id": self.trace_id,
            "timestamp": self.start_time,
            "query": self.query,
            "outcome": outcome,  # e.g. "diagnostic_results" | "refusal"
            "total_latency_ms": total_ms,
            "steps": self.steps,
        }
        _append_jsonl(TRACE_LOG_PATH, record)
        return record


class ObservabilityLogger:
    """Central logging facade used by agent.py. Wraps the lower-level
    log/trace writers behind a small, stable API."""

    def log_tool_call(self, code: str, success: bool, latency_ms: float, error: str = None) -> None:
        """Log (Diary entry) for a single lookup_dtc call."""
        record = {
            "timestamp": time.time(),
            "event": "tool_call",
            "tool": "lookup_dtc",
            "code": code,
            "success": success,
            "latency_ms": round(latency_ms, 3),
        }
        if error:
            record["error"] = error
        _append_jsonl(TOOL_LOG_PATH, record)

    @contextmanager
    def trace_query(self, query: str):
        """Context manager that yields a QueryTrace, automatically finishing
        and writing it on exit. Usage:

            with logger.trace_query(query) as trace:
                trace.step("extract_codes", codes=codes)
                ... do work ...
                trace.set_outcome("diagnostic_results")
        """
        trace = QueryTrace(query)
        trace._outcome = "unknown"

        def set_outcome(outcome: str) -> None:
            trace._outcome = outcome

        trace.set_outcome = set_outcome

        try:
            yield trace
        finally:
            trace.finish(trace._outcome)


_logger_singleton = None


def get_logger() -> ObservabilityLogger:
    """Return the shared ObservabilityLogger instance."""
    global _logger_singleton
    if _logger_singleton is None:
        _logger_singleton = ObservabilityLogger()
    return _logger_singleton


# --------------------------------------------------------------------------
# Metrics: aggregate stats computed from the logs written above.
# --------------------------------------------------------------------------

def _read_jsonl(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def compute_tool_metrics() -> dict:
    """Metrics derived from tool_calls.jsonl: success rate, average latency,
    most frequently looked-up codes, and failure breakdown."""
    records = _read_jsonl(TOOL_LOG_PATH)

    if not records:
        return {"total_calls": 0}

    total = len(records)
    successes = sum(1 for r in records if r.get("success"))
    failures = total - successes
    avg_latency = sum(r.get("latency_ms", 0) for r in records) / total
    code_counts = Counter(r.get("code") for r in records)

    return {
        "total_calls": total,
        "successes": successes,
        "failures": failures,
        "success_rate": round(successes / total, 3),
        "average_latency_ms": round(avg_latency, 3),
        "most_queried_codes": code_counts.most_common(5),
    }


def compute_trace_metrics() -> dict:
    """Metrics derived from traces.jsonl: refusal rate, average end-to-end
    latency per query, and outcome breakdown."""
    records = _read_jsonl(TRACE_LOG_PATH)

    if not records:
        return {"total_queries": 0}

    total = len(records)
    outcome_counts = Counter(r.get("outcome") for r in records)
    refusals = outcome_counts.get("refusal", 0)
    avg_latency = sum(r.get("total_latency_ms", 0) for r in records) / total

    return {
        "total_queries": total,
        "outcome_breakdown": dict(outcome_counts),
        "refusal_rate": round(refusals / total, 3),
        "average_query_latency_ms": round(avg_latency, 3),
    }


def print_metrics_report() -> None:
    """Print a human-readable summary combining tool and trace metrics —
    the 'health report' pillar of observability."""
    tool_metrics = compute_tool_metrics()
    trace_metrics = compute_trace_metrics()

    print("=" * 60)
    print("DiagAssist Observability Report")
    print("=" * 60)

    print("\n-- Tool Call Metrics (lookup_dtc) --")
    if tool_metrics["total_calls"] == 0:
        print("No tool calls logged yet.")
    else:
        print(f"Total calls:          {tool_metrics['total_calls']}")
        print(f"Successes / Failures: {tool_metrics['successes']} / {tool_metrics['failures']}")
        print(f"Success rate:         {tool_metrics['success_rate'] * 100:.1f}%")
        print(f"Average latency:      {tool_metrics['average_latency_ms']:.3f} ms")
        print(f"Most queried codes:   {tool_metrics['most_queried_codes']}")

    print("\n-- Query Trace Metrics --")
    if trace_metrics["total_queries"] == 0:
        print("No traces logged yet.")
    else:
        print(f"Total queries:        {trace_metrics['total_queries']}")
        print(f"Outcome breakdown:    {trace_metrics['outcome_breakdown']}")
        print(f"Refusal rate:         {trace_metrics['refusal_rate'] * 100:.1f}%")
        print(f"Avg query latency:    {trace_metrics['average_query_latency_ms']:.3f} ms")

    print("=" * 60)


if __name__ == "__main__":
    print_metrics_report()
