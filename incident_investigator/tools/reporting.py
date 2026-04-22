from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from incident_investigator.agents.base import AgentOutput


def format_agent_detail(role: str, bullet_points: list[str]) -> str:
    lines = [f"Role: {role}", ""]
    lines.extend([f"- {point}" for point in bullet_points])
    return "\n".join(lines)


def build_final_report(metadata: dict, outputs: list["AgentOutput"]) -> dict:
    monitor = outputs[0].findings
    investigator = outputs[1].findings
    root_cause = outputs[2].findings
    actions = outputs[3].findings

    anomalies = monitor["anomalies"]
    top_hypothesis = root_cause["hypotheses"][0]
    metric_summary = monitor.get("focused_metric_summary", monitor["metric_summary"])
    severity_summary = monitor.get("focused_severity_summary", monitor.get("severity_summary", {}))
    impacted_service = metric_summary["highest_latency_service"]

    return {
        "anomaly_summary": {
            "headline": metadata["title"],
            "summary": metadata["summary"],
            "severity": severity_summary.get("severity", monitor.get("incident_severity", metadata["severity"])),
            "impacted_service": impacted_service,
            "time_window": investigator["primary_window"],
        },
        "root_causes": root_cause["hypotheses"],
        "recommended_actions": actions["recommended_actions"],
        "supporting_evidence": [
            anomaly["description"] for anomaly in anomalies
        ] + top_hypothesis["evidence"],
        "inspection_targets": actions["inspection_targets"],
        "agent_trace": [
            {
                "agent": output.agent,
                "summary": output.summary,
                "detail": output.detail,
            }
            for output in outputs
        ],
    }
