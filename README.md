# Incident Investigator MVP

Hackathon-friendly multi-agent incident investigation demo for operational anomalies.

## What it is

This project simulates an operations-aware AI system that:

- monitors logs, metrics, traces, and user events
- detects unusual behavior
- investigates suspicious components and time windows
- ranks root-cause hypotheses
- recommends mitigations and next actions

It is intentionally built as an incident investigation workflow, not a generic code agent.

## Agent roles

- `MonitorAgent`: detects anomalies across logs, metrics, and user events
- `InvestigatorAgent`: gathers evidence and narrows time windows/components
- `RootCauseAgent`: generates and ranks explanations
- `ActionAgent`: recommends mitigations, fixes, and inspection targets
- `CoordinatorAgent`: orchestrates the workflow and prepares the final report

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Demo scenarios

- `checkout_latency_incident`: checkout API slowdown, Redis saturation, payment timeouts, and user conversion drop
- `search_relevance_regression`: search API error spike and user search abandonment after a model/config rollout

## Project layout

- `app.py`: Streamlit UI
- `incident_investigator/agents`: agent definitions
- `incident_investigator/tools`: investigation tools
- `incident_investigator/orchestration`: coordinator flow
- `incident_investigator/data`: mock operational data

