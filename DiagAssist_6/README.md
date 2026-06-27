# 🚗 DiagAssist – Autonomous Automotive Repair Planner

> **Google ADK • Gemini • MCP • A2A • Streamlit • SQLite • Vertex AI**

DiagAssist is an autonomous automotive diagnostic and repair planning assistant that transforms **Diagnostic Trouble Codes (DTCs)** into grounded, explainable repair plans using **Google Agent Development Kit (ADK)**, **Gemini**, **Model Context Protocol (MCP)**, and a structured automotive knowledge base.

Unlike conventional diagnostic tools that only display fault codes, DiagAssist reasons over technician queries, autonomously invokes diagnostic tools, retrieves verified repair knowledge, coordinates with external agents, and generates structured repair recommendations through an interactive Streamlit dashboard.

The system supports two execution modes:

* **Google ADK + Gemini Mode** – AI-powered reasoning with tool calling and natural-language explanations.
* **Offline Diagnostic Mode** – Rule-based fallback that ensures uninterrupted operation when cloud services are unavailable.

Developed as part of the **Google AI Agent Development Kit Capstone**, the project demonstrates real-world enterprise agent architecture using ADK, MCP, A2A communication, observability, memory, and grounded tool execution.

---

## ✨ Features

* 🤖 Google Agent Development Kit (ADK) powered diagnostic agent
* 🧠 Gemini-powered reasoning with autonomous Function Tool calling
* 🔌 Model Context Protocol (MCP) server exposing automotive diagnostic tools
* 🚗 SQLite knowledge base containing automotive Diagnostic Trouble Codes (DTCs)
* 💬 Interactive Streamlit dashboard for technician-friendly diagnostics
* 📄 PDF repair report generation
* 🧠 Short-term conversation memory and persistent diagnostic history
* 🔍 Grounded responses using verified repair data (no hallucinated repair steps)
* 📊 Observability with tool-call tracing and diagnostic metrics
* 🤝 A2A (Agent-to-Agent) communication for external Parts Agent integration
* ☁ Vertex AI authentication support using Application Default Credentials (ADC)
* 🔄 Automatic Offline Diagnostic Engine fallback when Gemini is unavailable
* 📈 Easily extensible DTC database supporting additional manufacturer codes

---

## Why AI Agents?

Traditional vehicle diagnostic tools simply display fault codes and leave technicians to search service manuals manually.

DiagAssist demonstrates how autonomous AI agents can significantly improve this workflow by:

* Understanding natural-language technician requests
* Deciding when diagnostic tools should be invoked
* Retrieving grounded repair knowledge
* Maintaining conversational context across multiple interactions
* Coordinating with external agents using the A2A protocol
* Producing explainable repair recommendations instead of raw data

This project showcases how Google ADK enables enterprise-grade intelligent agents that combine reasoning, memory, tool use, and structured workflows.

---

## System Architecture

```text
                       User
                         │
                         ▼
                 Streamlit Dashboard
                         │
                         ▼
               Google ADK Diagnostic Agent
                         │
      ┌──────────────────┼───────────────────┐
      │                  │                   │
      ▼                  ▼                   ▼
   Gemini AI        MCP Function Tool     Memory
      │                  │                   │
      ▼                  ▼                   ▼
 Tool Reasoning     SQLite DTC DB      Conversation History
      │
      ▼
  Observability + Logging
      │
      ▼
 Optional Parts Agent (A2A)
      │
      ▼
 Repair Report + PDF Export
```

See `specs/technical_design.md` for the full design document, data flow, risks, and mitigations.

---

## Repository Structure

```
DiagAssist/
│
├── specs/
│   └── technical_design.md
├── database/
│   ├── dtc_data.json
│   ├── database.py
│   └── dtc_database.db        (generated)
├── skills/
│   └── diagnostic-troubleshooting/
│       └── SKILL.md
├── mcp/
│   └── mcp_server.py
├── ui/
│   └── ui_renderer.py
├── tests/
│   └── evals.py
├── agent.py
├── agent_adk.py               (Google ADK integration)
├── main.py
├── streamlit_app.py           (Interactive web UI)
├── README.md
├── requirements.txt
└── pitch.md
```

---

## Setup Instructions

### 1. Clone / Extract the Project

```bash
cd DiagAssist
```

### 2. Create a Virtual Environment (Recommended)

```bash
python -m venv venv
source venv/bin/activate   # on Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Build the Local Database

```bash
cd database
python database.py
cd ..
```

This reads `database/dtc_data.json` and creates `database/dtc_database.db`.

---

## Live Demonstration

### Streamlit Dashboard (Recommended)

Launch the interactive Streamlit interface:

```bash
streamlit run streamlit_app.py
```

Users can:

* Enter Diagnostic Trouble Codes
* Ask automotive repair questions
* Receive AI-generated repair plans
* View grounded diagnostic explanations
* Export professional repair reports as PDF
* Observe automatic switching between ADK and Offline modes

### Running the MCP Server

The MCP server can be run standalone (useful for testing with any MCP client,
or wiring into a different agent framework):

```bash
cd mcp
python mcp_server.py
```

It communicates over stdio and exposes one tool: `lookup_dtc(code: str)`.

### Running the Agent (CLI)

For the full interactive experience (agent + A2UI rendering together):

```bash
python main.py
```

Example session:

```
> P0420

┌─ Repair Card: P0420 ───────────────────────────
│ Severity:     🟡 MEDIUM
│ Repair Time:  2 Hours
│
│ Description:
│   Catalyst System Efficiency Below Threshold (Bank 1)...
│
│ Checklist:
│ ✓ Inspect catalytic converter for physical damage or contamination
│ ✓ Check upstream and downstream O2 sensors for correct operation
│ ✓ Verify there are no exhaust leaks before or after the catalyst
│ ✓ Clear the code and perform a drive cycle to confirm repair
└───────────────────────────────────────────────────
```

You can also run the agent without the UI layer:

```bash
python agent.py
```

---

## Technology Stack

| Category             | Technology          | Purpose                           |
| -------------------- | ------------------- | --------------------------------- |
| AI Agent Framework   | Google ADK          | Agent orchestration               |
| Large Language Model | Gemini              | Natural language reasoning        |
| Agent Communication  | MCP, A2A            | Tool definitions & multi-agent    |
| Frontend             | Streamlit           | Interactive web dashboard         |
| Database             | SQLite              | Automotive DTC knowledge base     |
| Programming Language | Python              | Core implementation               |
| Authentication       | Vertex AI ADC       | Secure credential management      |
| Reporting            | ReportLab           | PDF generation                    |
| Logging              | JSONL Observability | Tool call tracing & metrics       |

---

## Running Evaluations

```bash
python tests/evals.py
```

This runs 7 automated test cases (valid code, natural-language question,
off-topic refusal, invalid code, multiple codes, malformed code handling,
and a memory follow-up test) and prints a pass/fail report. The script
exits with a non-zero status if any test fails, so it can be wired into CI.

---

## Sessions & Memory (Day 3)

Every `DiagAssistAgent` instance keeps:
- **Working memory** — the last few DTC lookups in the current process, so
  follow-up questions like "how serious is that?" resolve against the most
  recently discussed code without repeating it.
- **Long-term memory** — every lookup is appended to `memory/history.jsonl`,
  which persists across process restarts.

Try it:
```bash
python main.py
> P0420
> how serious is that?
```

---

## Observability & Grounding Evaluation (Day 4)

```bash
python observability.py   # prints a metrics report from logged activity
python judge.py            # checks that responses are faithfully grounded
```

- `observability.py` — structured logs (`logs/tool_calls.jsonl`) and traces
  (`logs/traces.jsonl`) of every query, plus an aggregate metrics report
  (success rate, refusal rate, latency, most-queried codes).
- `judge.py` — a deterministic grounding judge that checks every fact in a
  rendered response (severity, time, repair steps) against the raw
  `lookup_dtc` tool output, catching any fabricated or altered facts. It
  also includes `llm_judge_prompt()`, a ready-to-use prompt for a real
  LLM-as-Judge evaluation of clarity/tone (requires a Gemini API key to
  actually execute — see `agent_adk.py`).

---

## Real ADK Agent (Optional)

`agent_adk.py` swaps the rule-based agent for a real `google.adk.agents.Agent`
with `lookup_dtc` registered as a proper `FunctionTool`. Requires
`pip install google-adk` and a `GOOGLE_API_KEY` with active Gemini quota.

To use ADK mode:
```bash
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"
export GOOGLE_GENAI_USE_VERTEXAI=TRUE

python main.py
# Choose: 1 (Google ADK + Gemini Mode)
```

---

## Real MCP Protocol Test

```bash
python tests/test_mcp_client.py
```

Spawns `mcp_server.py` as a subprocess and talks to it over the actual MCP
stdio protocol (not just a direct function call) — confirms tool
registration and both successful and "not found" lookups work end-to-end.

---

## A2A Protocol — Multi-Agent Demo (Day 5)

DiagAssist's Diagnosis Agent can call a second, fully independent agent —
the **Parts Agent** — over HTTP, following the A2A pattern of Agent Card
discovery followed by task-based message passing between separate
processes.

> **Note on SDK versioning:** the official `a2a-sdk` package implements its
> Agent Card and message types as protobuf messages in current releases, a
> notably different and heavier surface than the pydantic-based API shown
> in most A2A tutorials. `a2a/parts_agent_server.py` and
> `a2a/a2a_client.py` implement the same core A2A pattern (Agent Card +
> task messages between independent agents) using plain FastAPI/httpx so
> it's runnable today. Swapping in the official SDK later only requires
> replacing the FastAPI routes — the agent logic itself doesn't change.

**Run the Parts Agent** (in its own terminal):
```bash
python a2a/parts_agent_server.py
# Listens on http://127.0.0.1:8001
```

**Check its Agent Card** (in another terminal):
```bash
curl http://127.0.0.1:8001/.well-known/agent.json
```

**Run the main app** — with the Parts Agent running, every successful DTC
lookup now also shows a "Likely Parts Needed (via Parts Agent / A2A)"
section, fetched live from the second agent:
```bash
python main.py
> P0420
```

If the Parts Agent isn't running, DiagAssist degrades gracefully — the
diagnostic response still works, it just omits the parts estimate.

---

## Screenshots

> Coming soon:
> * Dashboard Home
> * ADK Connected
> * Diagnostic Center
> * AI Repair Planning
> * PDF Report
> * Agent Activity Timeline
> * System Status
> * Observability Dashboard

`[ Screenshot 1: CLI session showing a successful P0420 lookup ]`

`[ Screenshot 2: evals.py pass/fail report ]`

---

## Future Improvements

* Expand to 5,000+ manufacturer-specific DTCs
* Live OBD-II integration using ELM327
* Multi-vehicle diagnostic history
* Voice-based technician assistant
* Cloud deployment on Google Cloud Run
* Fleet management integration
* Predictive maintenance recommendations
* Multi-agent repair workflow planning
* Real-time parts inventory integration
* Mobile technician application

---

## Acknowledgements

This project was built using:

* **Google Agent Development Kit (ADK)** – Agent orchestration framework
* **Google Gemini** – Large language model for reasoning
* **Google Cloud Vertex AI** – Managed API infrastructure
* **Model Context Protocol (MCP)** – Standard tool definitions
* **Streamlit** – Web dashboard framework
* **SQLite** – Embedded relational database
* **Python** – Programming language
* **ReportLab** – PDF generation

Special thanks to the **Google ADK Capstone Program** for providing the opportunity to explore autonomous agent development for real-world enterprise applications.

---

## License

This project is released under the **MIT License**.

---

## Support

For issues, questions, or contributions:
- Review the `specs/technical_design.md` for detailed architecture
- Check `skills/diagnostic-troubleshooting/SKILL.md` for agent behavior
- Run `python tests/evals.py` to verify the system works end-to-end
- See `agent_adk.py` for real ADK integration examples

---

**Built for the Google ADK Track. Production-ready autonomous agent architecture.** 🚗✨
