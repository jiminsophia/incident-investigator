from __future__ import annotations

from collections import Counter

from incident_investigator.agents.base import AgentOutput, BaseAgent
from incident_investigator.tools.anomaly_detector import detect_anomalies
from incident_investigator.tools.config_retriever import retrieve_relevant_artifacts
from incident_investigator.tools.log_parser import summarize_logs
from incident_investigator.tools.metrics import summarize_metrics
from incident_investigator.tools.reporting import format_agent_detail
from incident_investigator.tools.severity import calculate_incident_severity
from incident_investigator.tools.traces import summarize_traces
from incident_investigator.tools.user_behavior import summarize_user_behavior


class MonitorAgent(BaseAgent):
    name = "Monitor Agent"
    role = "Detect operational anomalies"

    def run(self, context: dict) -> AgentOutput:
        metric_summary = summarize_metrics(context["metrics"])
        log_summary = summarize_logs(context["logs"])
        user_summary = summarize_user_behavior(context["user_events"])
        severity = calculate_incident_severity(metric_summary, log_summary, user_summary)
        severity_summary = {
            "severity": severity["incident_severity"],
            "incident_score": severity["incident_score"],
            "affected_services": metric_summary.get("degraded_services", []),
            "summary": severity["summary"],
        }
        anomalies = detect_anomalies(metric_summary, log_summary, user_summary, severity_summary)

        findings = {
            "metric_summary": metric_summary,
            "log_summary": log_summary,
            "user_summary": user_summary,
            "severity_summary": severity_summary,
            "anomalies": anomalies,
        }
        detail = format_agent_detail(
            self.role,
            [
                f"Detected {len(anomalies)} anomalies across metrics, logs, and user signals.",
                f"Peak latency service: {metric_summary['highest_latency_service']}.",
                f"Error hotspot: {log_summary['top_error_component']}.",
                f"User impact: {user_summary['dropoff_summary']}",
            ],
        )
        return AgentOutput(
            agent=self.name,
            summary="Anomaly detection complete",
            findings=findings,
            detail=detail,
        )


class InvestigatorAgent(BaseAgent):
    name = "Investigator Agent"
    role = "Gather evidence and narrow suspicious components"

    def run(self, context: dict) -> AgentOutput:
        monitor = context["monitor"]
        trace_summary = summarize_traces(context["traces"])
        relevant_artifacts = retrieve_relevant_artifacts(
            context["artifacts"],
            monitor["log_summary"]["top_error_component"],
            monitor["metric_summary"]["highest_latency_service"],
            trace_summary["suspicious_span_names"],
        )

        suspicious_components = [
            monitor["log_summary"]["top_error_component"],
            monitor["metric_summary"]["highest_latency_service"],
            *trace_summary["hot_services"],
        ]
        component_counts = Counter(suspicious_components)

        findings = {
            "trace_summary": trace_summary,
            "relevant_artifacts": relevant_artifacts,
            "suspicious_components": component_counts.most_common(4),
            "primary_window": trace_summary["primary_window"],
        }
        detail = format_agent_detail(
            self.role,
            [
                f"Focused on incident window {trace_summary['primary_window']}.",
                "Trace bottlenecks concentrated in "
                f"{', '.join(trace_summary['hot_services']) or 'no clear hotspot yet'}.",
                f"Retrieved {len(relevant_artifacts)} related code/config references.",
            ],
        )
        return AgentOutput(
            agent=self.name,
            summary="Evidence gathered",
            findings=findings,
            detail=detail,
        )


class RootCauseAgent(BaseAgent):
    name = "Root Cause Agent"
    role = "Rank likely explanations"

    def run(self, context: dict) -> AgentOutput:
        monitor = context["monitor"]
        investigator = context["investigator"]
        anomalies = monitor["anomalies"]

        if not anomalies:
            hypotheses = [
                {
                    "title": "Insufficient evidence for a confirmed incident",
                    "confidence": "Low",
                    "rationale": (
                        "Latency, logs, and user behavior are still close to baseline, so the "
                        "system is monitoring for stronger cross-signal confirmation."
                    ),
                    "evidence": [
                        monitor["metric_summary"]["latency_summary"],
                        monitor["log_summary"]["error_summary"],
                        monitor["user_summary"]["dropoff_summary"],
                    ],
                }
            ]
            findings = {"hypotheses": hypotheses}
            detail = format_agent_detail(
                self.role,
                [
                    "Held off on a strong root-cause claim because the signal is still weak.",
                    "Waiting for stronger alignment across metrics, errors, traces, and user impact.",
                ],
            )
            return AgentOutput(
                agent=self.name,
                summary="Monitoring for stronger evidence",
                findings=findings,
                detail=detail,
            )

        top_error = monitor["log_summary"]["top_error_component"]
        top_latency = monitor["metric_summary"]["highest_latency_service"]
        artifact_titles = [item["title"] for item in investigator["relevant_artifacts"]]

        hypotheses = [
            {
                "title": f"{top_latency} dependency saturation caused cascading latency",
                "confidence": "High",
                "rationale": (
                    f"{top_latency} shows the highest latency spike, traces indicate queueing, "
                    "and logs show timeout symptoms during the same time window."
                ),
                "evidence": [
                    monitor["metric_summary"]["latency_summary"],
                    investigator["trace_summary"]["trace_summary"],
                    f"Related artifacts: {', '.join(artifact_titles[:2]) or 'none'}",
                ],
            },
            {
                "title": f"{top_error} rollout/config change introduced request failures",
                "confidence": "Medium",
                "rationale": (
                    f"{top_error} dominates the error logs and the retrieved artifacts include "
                    "recently changed rollout or timeout settings connected to the incident path."
                ),
                "evidence": [
                    monitor["log_summary"]["error_summary"],
                    f"Primary incident window: {investigator['primary_window']}",
                    f"Artifact matches: {', '.join(artifact_titles[2:4]) or 'limited matches'}",
                ],
            },
        ]

        findings = {"hypotheses": hypotheses}
        detail = format_agent_detail(
            self.role,
            [
                f"Ranked {len(hypotheses)} root-cause hypotheses.",
                f"Top hypothesis links {top_latency} latency with downstream timeout behavior.",
            ],
        )
        return AgentOutput(
            agent=self.name,
            summary="Root-cause hypotheses ranked",
            findings=findings,
            detail=detail,
        )


class ActionAgent(BaseAgent):
    name = "Action Agent"
    role = "Recommend mitigation and follow-up actions"

    def run(self, context: dict) -> AgentOutput:
        root_causes = context["root_cause"]["hypotheses"]
        investigator = context["investigator"]
        artifacts = investigator["relevant_artifacts"]

        if root_causes[0]["confidence"] == "Low":
            actions = [
                "Keep the incident in watch mode and continue collecting the next few minutes of logs, traces, and user metrics.",
                "Alert the on-call owner for the suspected service path, but avoid rollback until cross-signal evidence strengthens.",
                "Prepare the matched runbook and recent rollout/config diffs so responders can move quickly if severity increases.",
            ]
            inspection_targets = [artifact["location"] for artifact in artifacts]
            findings = {
                "recommended_actions": actions,
                "inspection_targets": inspection_targets,
            }
            detail = format_agent_detail(
                self.role,
                [
                    "Recommended low-risk watch actions because the incident is not yet confirmed.",
                    f"Flagged {len(inspection_targets)} early inspection targets.",
                ],
            )
            return AgentOutput(
                agent=self.name,
                summary="Watch-mode actions prepared",
                findings=findings,
                detail=detail,
            )

        actions = [
            "Mitigate user impact first: roll back the latest risky config or feature gate on the affected request path.",
            "Reduce pressure on the hot dependency with cache warming, connection pool checks, or temporary traffic shaping.",
            "Inspect timeout, retry, and circuit-breaker settings for the impacted service chain during the incident window.",
            "Review the matched code/config artifacts and compare against the last known healthy deployment.",
            "Add a targeted alert that joins latency, timeout errors, and conversion drop for earlier detection next time.",
        ]
        inspection_targets = [artifact["location"] for artifact in artifacts]

        findings = {
            "recommended_actions": actions,
            "inspection_targets": inspection_targets,
        }
        detail = format_agent_detail(
            self.role,
            [
                f"Produced {len(actions)} recommended actions.",
                f"Flagged {len(inspection_targets)} code/config locations for inspection.",
            ],
        )
        return AgentOutput(
            agent=self.name,
            summary="Actions prepared",
            findings=findings,
            detail=detail,
        )
