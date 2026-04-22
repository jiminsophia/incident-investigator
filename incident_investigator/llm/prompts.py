from __future__ import annotations

import json


def build_agentic_system_prompt() -> str:
    return """
You are an expert SRE incident investigator operating as a tool-using agent.

Your job is to investigate the incident by calling available skill tools, then return a final JSON report.

Rules:
- Prefer tool calls for evidence gathering, correlation, and review.
- Use the investigation state tool whenever you need to see what is already known.
- Do not invent logs, traces, artifacts, time windows, or config changes that were not provided by tools.
- If a tool fails or returns weak evidence, adapt by choosing another tool or retrying later.
- Once you have enough evidence, return only valid JSON with this exact top-level shape:
{
  "anomaly_summary": {
    "headline": "string",
    "summary": "string",
    "severity": "string",
    "impacted_service": "string",
    "time_window": "string"
  },
  "root_causes": [
    {
      "title": "string",
      "confidence": "Low|Medium|High",
      "rationale": "string",
      "evidence": ["string"]
    }
  ],
  "recommended_actions": ["string"],
  "supporting_evidence": ["string"],
  "inspection_targets": ["string"],
  "llm_summary": "string"
}
- Return JSON only when finishing. No markdown fences.
""".strip()


def build_agentic_user_prompt(bundle: dict) -> str:
    payload = {
        "metadata": bundle["metadata"],
        "dataset_sizes": {
            "logs": len(bundle.get("logs", [])),
            "metrics": len(bundle.get("metrics", [])),
            "traces": len(bundle.get("traces", [])),
            "user_events": len(bundle.get("user_events", [])),
            "artifacts": len(bundle.get("artifacts", [])),
        },
        "replay_stage": bundle.get("replay_stage"),
    }
    return (
        "Investigate this incident. Gather evidence with tool calls before producing the final report.\n\n"
        + json.dumps(payload, indent=2)
    )


def build_hypothesis_prompt(context: dict) -> str:
    payload = {
        "metadata": context["metadata"],
        "metric_summary": context["metric_summary"],
        "log_summary": context["log_summary"],
        "user_summary": context["user_summary"],
        "trace_summary": context.get("trace_summary", {}),
        "primary_window": context.get("primary_window"),
        "relevant_artifacts": context.get("relevant_artifacts", []),
        "anomalies": context["anomalies"],
    }
    return json.dumps(payload, indent=2)


def build_action_prompt(context: dict) -> str:
    payload = {
        "metadata": context["metadata"],
        "hypotheses": context["hypotheses"],
        "evidence_gaps": context.get("evidence_gaps", []),
        "relevant_artifacts": context.get("relevant_artifacts", []),
        "primary_window": context.get("primary_window"),
    }
    return json.dumps(payload, indent=2)
