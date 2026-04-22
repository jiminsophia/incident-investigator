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
            "raw_events": len(bundle.get("raw_events", [])),
            "baseline_events": len(bundle.get("baseline_events", [])),
            "traces": len(bundle.get("traces", [])),
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
        "incident_severity": context.get("incident_severity"),
        "metric_summary": context.get("focused_metric_summary", context["metric_summary"]),
        "log_summary": context.get("focused_log_summary", context["log_summary"]),
        "user_summary": context.get("focused_user_summary", context["user_summary"]),
        "request_path_summary": context.get("focused_request_path_summary", context.get("request_path_summary", {})),
        "severity_summary": context.get("focused_severity_summary", context.get("severity_summary", {})),
        "trace_summary": context.get("trace_summary", {}),
        "focused_window": context.get("focused_window"),
        "primary_window": context.get("primary_window"),
        "relevant_artifacts": context.get("relevant_artifacts", []),
        "anomalies": context["anomalies"],
    }
    return json.dumps(payload, indent=2)


def build_action_prompt(context: dict) -> str:
    payload = {
        "metadata": context["metadata"],
        "incident_severity": context.get("incident_severity"),
        "hypotheses": context["hypotheses"],
        "evidence_gaps": context.get("evidence_gaps", []),
        "relevant_artifacts": context.get("relevant_artifacts", []),
        "request_path_summary": context.get("focused_request_path_summary", context.get("request_path_summary", {})),
        "severity_summary": context.get("focused_severity_summary", context.get("severity_summary", {})),
        "focused_window": context.get("focused_window"),
        "primary_window": context.get("primary_window"),
    }
    return json.dumps(payload, indent=2)
