# Incident Investigator MVP

Skill-based incident investigation demo for operational anomalies.

## What it is

This project simulates an operations-aware AI system that:

- monitors logs, metrics, traces, and user events
- detects unusual behavior
- investigates suspicious components and time windows
- ranks root-cause hypotheses
- recommends mitigations and next actions
- replans investigation steps when a module returns weak evidence
- retries fragile steps like trace analysis before falling back to other evidence

It is intentionally built as an incident investigation workflow, not a generic code agent.

## Architecture

### README-friendly ASCII view

```text
                User Request / Demo Run
                 (Streamlit UI / CLI)
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    Incident Investigator App                        │
│                                                                      │
│  Entry points:                                                       │
│  - app.py                                                            │
│  - run_demo.py                                                       │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                      CoordinatorAgent                         │  │
│  │                                                              │  │
│  │  Chooses investigation mode:                                 │  │
│  │  - deterministic planner loop                                │  │
│  │  - LLM tool-calling loop                                     │  │
│  │                                                              │  │
│  │  Chooses execution backend:                                  │  │
│  │  - native Python                                             │  │
│  │  - NeMo Agent Toolkit (nemo_nat)                             │  │
│  │                                                              │  │
│  │  Shared runtime state:                                       │  │
│  │  - context                                                   │  │
│  │  - findings                                                  │  │
│  │  - trace                                                    │  │
│  │  - streamed events                                           │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                           │                                          │
│                           ▼                                          │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                     Investigation Skills                       │  │
│  │  - Signal Monitor                                             │  │
│  │  - Trace Investigation                                        │  │
│  │  - Artifact Analysis                                          │  │
│  │  - Component Correlation                                      │  │
│  │  - Hypothesis Generation                                      │  │
│  │  - Evidence Review                                            │  │
│  │  - Action Planning                                            │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       Data Assembly Layer                           │
│                                                                      │
│  load_scenario_bundle()                                              │
│  - reads incident manifest                                           │
│  - slices shared raw logs / traces / metrics / user events           │
│  - assembles the runtime investigation bundle                        │
│                                                                      │
│  data/incidents/*.json                                               │
│  data/raw/logs/*.jsonl                                               │
│  data/raw/traces/*.jsonl                                             │
│  data/raw/metrics/*.json                                             │
│  data/raw/user_events/*.json                                         │
│  data/raw/artifacts/*.json                                           │
└──────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
              Streamed Timeline / Final Incident Report
          ┌──────────────────────────────────────────────┐
          │ Streamlit UI  │  Rich CLI  │  Plain CLI     │
          └──────────────────────────────────────────────┘
```

### Code structure view

```text
incident-investigator/
├── app.py
│   └── Streamlit entrypoint
│       - scenario selection
│       - investigation thread / queue
│       - live event feed and final report rendering
│
├── run_demo.py
│   └── Terminal entrypoint
│       - plain / rich CLI output
│       - JSONL event logging
│       - execution backend selection
│
└── incident_investigator/
    ├── orchestration/
    │   └── coordinator.py
    │       └── CoordinatorAgent
    │           - starts the investigation
    │           - chooses planner or LLM tool-calling path
    │           - emits execution events
    │           - finalizes the incident report
    │
    ├── planning/
    │   ├── state.py
    │   │   └── ExecutionState
    │   │       - shared context, findings, event stream, trace
    │   ├── planner.py
    │   │   └── InvestigationPlanner
    │   │       - chooses the next skill in deterministic mode
    │   └── validator.py
    │       └── ResultValidator
    │           - checks result quality and decides on retry/fallback
    │
    ├── llm/
    │   ├── client.py
    │   │   └── LLMClient
    │   │       - OpenAI-compatible streaming client
    │   │       - streamed content + tool-call reconstruction
    │   ├── tool_calling.py
    │   │   └── ToolCallingInvestigator
    │   │       - LLM-led investigation loop
    │   │       - exposes investigation tools to the model
    │   └── prompts.py
    │       └── prompt builders for investigation / hypotheses / actions
    │
    ├── execution.py
    │   └── Skill execution backends
    │       - DirectSkillExecutor
    │       - NemoNATSkillExecutor
    │
    ├── skills/
    │   ├── base.py
    │   │   └── BaseSkill / SkillResult / SkillSpec
    │   ├── registry.py
    │   │   └── SkillRegistry
    │   └── modules.py
    │       └── concrete skills
    │           - SignalMonitorSkill
    │           - TraceInvestigationSkill
    │           - ArtifactAnalysisSkill
    │           - ComponentCorrelationSkill
    │           - HypothesisGenerationSkill
    │           - EvidenceReviewSkill
    │           - ActionPlanningSkill
    │
    ├── tools/
    │   ├── data_loader.py
    │   │   └── data assembly
    │   │       - list_scenarios()
    │   │       - load_scenario_bundle()
    │   │       - build_replay_bundle()
    │   ├── metrics.py
    │   ├── log_parser.py
    │   ├── traces.py
    │   ├── user_behavior.py
    │   └── config_retriever.py
    │       └── low-level summarizers and retrieval helpers
    │
    └── data/
        ├── raw/
        │   ├── logs/application_logs.jsonl
        │   ├── traces/distributed_traces.jsonl
        │   ├── metrics/service_metrics.json
        │   ├── user_events/conversion_snapshots.json
        │   └── artifacts/catalog.json
        │
        └── incidents/
            ├── checkout_latency_incident.json
            └── search_relevance_regression.json
            └── incident manifests
                - metadata shown to the user
                - filters for slicing shared raw data
                - optional replay stages
```

## Data layout

The demo now uses a more real-data-like structure:

- `incident_investigator/data/raw/`: shared observability-style datasets
- `incident_investigator/data/incidents/`: incident manifests that describe how to slice the raw data

Each incident manifest defines:

- the incident metadata shown in the UI
- the time window, services, components, and flows to pull from raw logs/traces/metrics/user events
- optional replay stages that progressively widen the slice to simulate the investigation over time

This means the app no longer assumes that logs or user events are pre-organized into per-incident folders. The loader assembles the investigation bundle at runtime from shared raw datasets, and those raw datasets intentionally include healthy traffic and unrelated noise alongside the incident signals.

## Skill-based flow

- `Signal Monitor`: summarizes metrics, logs, and user impact, then detects anomalies
- `Trace Investigation`: inspects slow traces and narrows the primary incident window
- `Artifact Analysis`: finds related code/config artifacts for suspected services
- `Component Correlation`: combines outputs into ranked suspicious components
- `Hypothesis Generation`: creates and scores likely root-cause explanations
- `Evidence Review`: checks whether the current evidence is strong enough
- `Action Planning`: recommends mitigations and next actions
- `CoordinatorAgent`: plans which skill to run next and retries weak steps automatically

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## vLLM API

This project can optionally call a vLLM server through its OpenAI-compatible API.

## NeMo Agent Toolkit

This project now includes an optional NeMo Agent Toolkit execution path using the `nvidia-nat` package. When enabled, investigation skills are wrapped as NAT `LambdaFunction`s and executed through the NeMo Agent Toolkit function runtime.

Environment variables for `run_demo.py`:

```bash
export VLLM_API_BASE=http://localhost:8000/v1
export VLLM_MODEL=google/gemma-4-31b-it
export VLLM_API_KEY=EMPTY
python3 run_demo.py --execution-backend nemo_nat
```

`run_demo.py` now streams investigation events and live LLM output in the terminal by default.

- default mode uses a `rich` live dashboard
- use `--plain` for the simpler line-by-line terminal stream
- use `--jsonl-log logs/run.jsonl` to persist every streamed event
- use `--no-stream` if you only want the final JSON report
- use `--scenario-list` to list available scenarios
- use `--execution-backend nemo_nat` to execute skills through NeMo Agent Toolkit

In the Streamlit app, enable `Use vLLM API` in the sidebar and provide the same values there.
You can also choose `NeMo Agent Toolkit (NAT)` as the skill execution backend in the sidebar.

When vLLM is configured, the app switches to an LLM-led investigation loop:

- the model plans the investigation
- the model calls investigation skills as tools
- the model decides when to retry or switch skills
- the model synthesizes the final report

The deterministic planner remains as a fallback if tool calling is unavailable or the model does not return valid JSON.

## Demo scenarios

- `checkout_latency_incident`: checkout API slowdown, Redis saturation, payment timeouts, and user conversion drop
- `search_relevance_regression`: search API error spike and user search abandonment after a model/config rollout

## Project layout

- `app.py`: Streamlit UI
- `incident_investigator/data/raw`: shared mock logs, traces, metrics, user events, and artifact catalog
- `incident_investigator/data/incidents`: incident manifests used to slice raw data into investigation bundles
- `incident_investigator/skills`: skill definitions and registry
- `incident_investigator/planning`: planner, validator, and execution state
- `incident_investigator/agents`: legacy role-oriented agent definitions
- `incident_investigator/tools`: investigation tools
- `incident_investigator/orchestration`: coordinator flow
- `incident_investigator/data`: mock operational data

## Tests

```bash
python3 -m unittest discover -s tests
```
