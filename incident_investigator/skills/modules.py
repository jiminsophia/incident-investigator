from __future__ import annotations

from collections import Counter

from incident_investigator.llm.prompts import build_action_prompt, build_hypothesis_prompt
from incident_investigator.skills.base import BaseSkill, SkillResult, SkillSpec
from incident_investigator.tools.anomaly_detector import detect_anomalies
from incident_investigator.tools.config_retriever import retrieve_relevant_artifacts
from incident_investigator.tools.log_parser import summarize_logs
from incident_investigator.tools.metrics import summarize_metrics
from incident_investigator.tools.reporting import format_agent_detail
from incident_investigator.tools.traces import summarize_traces
from incident_investigator.tools.user_behavior import summarize_user_behavior


class SignalMonitorSkill(BaseSkill):
    spec = SkillSpec(
        name="Signal Monitor",
        description="Summarize logs, metrics, user behavior, and detect anomalies.",
        required_keys=("metrics", "logs", "user_events"),
        produced_keys=("metric_summary", "log_summary", "user_summary", "anomalies"),
    )

    def run(self, context: dict) -> SkillResult:
        metric_summary = summarize_metrics(context["metrics"])
        log_summary = summarize_logs(context["logs"])
        user_summary = summarize_user_behavior(context["user_events"])
        anomalies = detect_anomalies(metric_summary, log_summary, user_summary)

        confidence = min(1.0, 0.25 + 0.2 * len(anomalies))
        detail = format_agent_detail(
            "Detect operational anomalies",
            [
                f"Detected {len(anomalies)} anomalies across metrics, logs, and user signals.",
                f"Peak latency service: {metric_summary['highest_latency_service']}.",
                f"Error hotspot: {log_summary['top_error_component']}.",
                f"User impact: {user_summary['dropoff_summary']}",
            ],
        )
        return SkillResult(
            skill=self.spec.name,
            success=True,
            summary="Signal summaries updated",
            findings={
                "metric_summary": metric_summary,
                "log_summary": log_summary,
                "user_summary": user_summary,
                "anomalies": anomalies,
            },
            confidence=confidence,
            detail=detail,
        )


class TraceInvestigationSkill(BaseSkill):
    spec = SkillSpec(
        name="Trace Investigation",
        description="Inspect slow traces to identify the primary incident window.",
        required_keys=("traces",),
        produced_keys=("trace_summary",),
        max_retries=2,
    )

    def run(self, context: dict) -> SkillResult:
        trace_summary = summarize_traces(context["traces"])
        hot_services = trace_summary["hot_services"]
        confidence = 0.2 if not hot_services else min(0.85, 0.35 + 0.15 * len(hot_services))

        detail = format_agent_detail(
            "Gather trace evidence",
            [
                f"Focused on incident window {trace_summary['primary_window']}.",
                "Trace bottlenecks concentrated in "
                f"{', '.join(hot_services) or 'no clear hotspot yet'}.",
                trace_summary["trace_summary"],
            ],
        )
        return SkillResult(
            skill=self.spec.name,
            success=True,
            summary="Trace analysis complete",
            findings={"trace_summary": trace_summary},
            confidence=confidence,
            detail=detail,
        )


class ArtifactAnalysisSkill(BaseSkill):
    spec = SkillSpec(
        name="Artifact Analysis",
        description="Pull code and config artifacts related to the suspected incident path.",
        required_keys=("artifacts", "metric_summary", "log_summary"),
        produced_keys=("relevant_artifacts",),
    )

    def run(self, context: dict) -> SkillResult:
        trace_summary = context.get(
            "trace_summary",
            {"suspicious_span_names": [], "hot_services": [], "primary_window": "unknown"},
        )
        relevant_artifacts = retrieve_relevant_artifacts(
            context["artifacts"],
            context["log_summary"]["top_error_component"],
            context["metric_summary"]["highest_latency_service"],
            trace_summary["suspicious_span_names"],
        )
        confidence = 0.3 if not relevant_artifacts else min(0.9, 0.35 + 0.1 * len(relevant_artifacts))
        detail = format_agent_detail(
            "Retrieve code and config evidence",
            [
                f"Retrieved {len(relevant_artifacts)} related code/config references.",
                f"Primary lookup window remains {trace_summary['primary_window']}.",
            ],
        )
        return SkillResult(
            skill=self.spec.name,
            success=True,
            summary="Artifacts ranked",
            findings={"relevant_artifacts": relevant_artifacts},
            confidence=confidence,
            detail=detail,
        )


class ComponentCorrelationSkill(BaseSkill):
    spec = SkillSpec(
        name="Component Correlation",
        description="Correlate suspicious components across signals and traces.",
        required_keys=("metric_summary", "log_summary"),
        produced_keys=("suspicious_components", "primary_window"),
    )

    def run(self, context: dict) -> SkillResult:
        trace_summary = context.get(
            "trace_summary",
            {"hot_services": [], "primary_window": "not enough trace data yet"},
        )
        suspicious_components = [
            context["log_summary"]["top_error_component"],
            context["metric_summary"]["highest_latency_service"],
            *trace_summary["hot_services"],
        ]
        component_counts = Counter(component for component in suspicious_components if component)
        findings = {
            "suspicious_components": component_counts.most_common(4),
            "primary_window": trace_summary["primary_window"],
        }
        confidence = 0.25 if not findings["suspicious_components"] else 0.65
        detail = format_agent_detail(
            "Correlate evidence across modules",
            [
                f"Focused on incident window {trace_summary['primary_window']}.",
                "Cross-signal hotspots were "
                f"{', '.join(name for name, _ in findings['suspicious_components']) or 'not clear yet'}.",
            ],
        )
        return SkillResult(
            skill=self.spec.name,
            success=True,
            summary="Suspicious components ranked",
            findings=findings,
            confidence=confidence,
            detail=detail,
        )


class HypothesisGenerationSkill(BaseSkill):
    spec = SkillSpec(
        name="Hypothesis Generation",
        description="Generate and rank likely root-cause hypotheses.",
        required_keys=("anomalies", "metric_summary", "log_summary", "user_summary"),
        produced_keys=("hypotheses",),
    )

    def run(self, context: dict) -> SkillResult:
        llm_result = self._run_with_llm(context)
        if llm_result is not None and llm_result.success:
            return llm_result

        anomalies = context["anomalies"]
        trace_summary = context.get(
            "trace_summary",
            {
                "trace_summary": "Trace evidence is still thin.",
                "primary_window": "not enough trace data yet",
            },
        )
        relevant_artifacts = context.get("relevant_artifacts", [])
        top_error = context["log_summary"]["top_error_component"]
        top_latency = context["metric_summary"]["highest_latency_service"]
        artifact_titles = [item["title"] for item in relevant_artifacts]

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
                        context["metric_summary"]["latency_summary"],
                        context["log_summary"]["error_summary"],
                        context["user_summary"]["dropoff_summary"],
                    ],
                }
            ]
            confidence = 0.2
            detail_lines = [
                "Held off on a strong root-cause claim because the signal is still weak.",
                "Waiting for stronger alignment across metrics, errors, traces, and user impact.",
            ]
        else:
            has_trace_support = bool(trace_summary.get("hot_services"))
            has_artifact_support = bool(relevant_artifacts)
            hypotheses = [
                {
                    "title": f"{top_latency} dependency saturation caused cascading latency",
                    "confidence": "High" if has_trace_support else "Medium",
                    "rationale": (
                        f"{top_latency} shows the highest latency spike, traces indicate queueing, "
                        "and logs show timeout symptoms during the same time window."
                        if has_trace_support
                        else f"{top_latency} shows the highest latency spike and logs show timeout "
                        "symptoms, but trace confirmation is still limited."
                    ),
                    "evidence": [
                        context["metric_summary"]["latency_summary"],
                        trace_summary["trace_summary"],
                        f"Related artifacts: {', '.join(artifact_titles[:2]) or 'none'}",
                    ],
                },
                {
                    "title": f"{top_error} rollout/config change introduced request failures",
                    "confidence": "Medium" if has_artifact_support else "Low",
                    "rationale": (
                        f"{top_error} dominates the error logs and the retrieved artifacts include "
                        "recently changed rollout or timeout settings connected to the incident path."
                        if has_artifact_support
                        else f"{top_error} dominates the error logs, but artifact matches are still too thin "
                        "to strongly confirm a rollout or configuration issue."
                    ),
                    "evidence": [
                        context["log_summary"]["error_summary"],
                        f"Primary incident window: {context.get('primary_window', trace_summary['primary_window'])}",
                        f"Artifact matches: {', '.join(artifact_titles[2:4]) or 'limited matches'}",
                    ],
                },
            ]
            confidence = 0.55 + (0.15 if has_trace_support else 0.0) + (0.1 if has_artifact_support else 0.0)
            detail_lines = [
                f"Ranked {len(hypotheses)} root-cause hypotheses.",
                f"Top hypothesis links {top_latency} latency with downstream timeout behavior.",
            ]

        detail = format_agent_detail("Rank likely explanations", detail_lines)
        return SkillResult(
            skill=self.spec.name,
            success=True,
            summary="Root-cause hypotheses ranked",
            findings={"hypotheses": hypotheses},
            confidence=min(confidence, 0.95),
            detail=detail,
        )

    def _run_with_llm(self, context: dict) -> SkillResult | None:
        llm = context.get("llm_client")
        if llm is None:
            return None

        system_prompt = (
            "You are an incident investigation analyst. Return only valid JSON with this shape: "
            '{"hypotheses":[{"title":str,"confidence":"Low|Medium|High","rationale":str,"evidence":[str]}],'
            '"summary":str,"detail_points":[str],"confidence_score":number}. '
            "Use only the provided evidence. Do not invent unavailable logs, traces, or artifacts."
        )
        try:
            response = llm.generate_json(
                system_prompt,
                build_hypothesis_prompt(context),
                stream_handler=context.get("llm_stream_callback"),
                response_label="Hypothesis Generation",
            )
        except Exception as exc:
            return SkillResult(
                skill=self.spec.name,
                success=False,
                summary="LLM hypothesis generation failed",
                detail=f"Falling back to deterministic hypothesis generation.\n\nError: {exc}",
                errors=[str(exc)],
            )

        hypotheses = response.get("hypotheses", [])
        if not hypotheses:
            return SkillResult(
                skill=self.spec.name,
                success=False,
                summary="LLM hypothesis generation returned no hypotheses",
                detail="Falling back to deterministic hypothesis generation.",
                errors=["No hypotheses returned by the LLM."],
            )

        detail = format_agent_detail(
            "Rank likely explanations",
            response.get("detail_points", ["LLM-generated hypotheses were incorporated into the investigation."]),
        )
        return SkillResult(
            skill=self.spec.name,
            success=True,
            summary=response.get("summary", "LLM-generated root-cause hypotheses ranked"),
            findings={"hypotheses": hypotheses},
            confidence=float(response.get("confidence_score", 0.75)),
            detail=detail,
        )


class EvidenceReviewSkill(BaseSkill):
    spec = SkillSpec(
        name="Evidence Review",
        description="Review evidence coverage and decide whether the current case is strong enough.",
        required_keys=("hypotheses",),
        produced_keys=("investigation_confidence", "evidence_gaps"),
    )

    def run(self, context: dict) -> SkillResult:
        hypotheses = context["hypotheses"]
        relevant_artifacts = context.get("relevant_artifacts", [])
        trace_summary = context.get("trace_summary", {"slow_trace_count": 0})

        evidence_gaps = []
        if trace_summary.get("slow_trace_count", 0) == 0:
            evidence_gaps.append("Trace evidence is still limited.")
        if not relevant_artifacts:
            evidence_gaps.append("Matched code/config artifacts are limited.")
        if hypotheses and hypotheses[0]["confidence"] == "Low":
            evidence_gaps.append("Top hypothesis confidence is still low.")

        investigation_confidence = max(0.2, 0.8 - 0.15 * len(evidence_gaps))
        detail = format_agent_detail(
            "Review evidence completeness",
            [
                f"Found {len(evidence_gaps)} evidence gaps.",
                "Current evidence is strong enough to proceed."
                if not evidence_gaps
                else "Proceeding with a cautious report while keeping gaps visible.",
            ]
            + evidence_gaps,
        )
        return SkillResult(
            skill=self.spec.name,
            success=True,
            summary="Evidence coverage reviewed",
            findings={
                "investigation_confidence": investigation_confidence,
                "evidence_gaps": evidence_gaps,
            },
            confidence=investigation_confidence,
            detail=detail,
        )


class ActionPlanningSkill(BaseSkill):
    spec = SkillSpec(
        name="Action Planning",
        description="Recommend mitigation and follow-up actions.",
        required_keys=("hypotheses",),
        produced_keys=("recommended_actions", "inspection_targets"),
    )

    def run(self, context: dict) -> SkillResult:
        llm_result = self._run_with_llm(context)
        if llm_result is not None and llm_result.success:
            return llm_result

        hypotheses = context["hypotheses"]
        artifacts = context.get("relevant_artifacts", [])

        if hypotheses[0]["confidence"] == "Low":
            actions = [
                "Keep the incident in watch mode and continue collecting the next few minutes of logs, traces, and user metrics.",
                "Alert the on-call owner for the suspected service path, but avoid rollback until cross-signal evidence strengthens.",
                "Prepare the matched runbook and recent rollout/config diffs so responders can move quickly if severity increases.",
            ]
            summary = "Watch-mode actions prepared"
            detail_lines = [
                "Recommended low-risk watch actions because the incident is not yet confirmed.",
                f"Flagged {len(artifacts)} early inspection targets.",
            ]
        else:
            actions = [
                "Mitigate user impact first: roll back the latest risky config or feature gate on the affected request path.",
                "Reduce pressure on the hot dependency with cache warming, connection pool checks, or temporary traffic shaping.",
                "Inspect timeout, retry, and circuit-breaker settings for the impacted service chain during the incident window.",
                "Review the matched code/config artifacts and compare against the last known healthy deployment.",
                "Add a targeted alert that joins latency, timeout errors, and conversion drop for earlier detection next time.",
            ]
            summary = "Actions prepared"
            detail_lines = [
                f"Produced {len(actions)} recommended actions.",
                f"Flagged {len(artifacts)} code/config locations for inspection.",
            ]

        inspection_targets = [artifact["location"] for artifact in artifacts]
        detail = format_agent_detail("Recommend mitigation and follow-up actions", detail_lines)
        return SkillResult(
            skill=self.spec.name,
            success=True,
            summary=summary,
            findings={
                "recommended_actions": actions,
                "inspection_targets": inspection_targets,
            },
            confidence=0.75 if actions else 0.25,
            detail=detail,
        )

    def _run_with_llm(self, context: dict) -> SkillResult | None:
        llm = context.get("llm_client")
        if llm is None:
            return None

        system_prompt = (
            "You are an SRE incident commander assistant. Return only valid JSON with this shape: "
            '{"summary":str,"recommended_actions":[str],"inspection_targets":[str],"detail_points":[str],"confidence_score":number}. '
            "Keep actions concrete, safe, and grounded in the supplied evidence."
        )
        try:
            response = llm.generate_json(
                system_prompt,
                build_action_prompt(context),
                stream_handler=context.get("llm_stream_callback"),
                response_label="Action Planning",
            )
        except Exception as exc:
            return SkillResult(
                skill=self.spec.name,
                success=False,
                summary="LLM action planning failed",
                detail=f"Falling back to deterministic action planning.\n\nError: {exc}",
                errors=[str(exc)],
            )

        actions = response.get("recommended_actions", [])
        if not actions:
            return SkillResult(
                skill=self.spec.name,
                success=False,
                summary="LLM action planning returned no actions",
                detail="Falling back to deterministic action planning.",
                errors=["No actions returned by the LLM."],
            )

        detail = format_agent_detail(
            "Recommend mitigation and follow-up actions",
            response.get("detail_points", ["LLM-generated actions were incorporated into the final plan."]),
        )
        return SkillResult(
            skill=self.spec.name,
            success=True,
            summary=response.get("summary", "LLM-generated actions prepared"),
            findings={
                "recommended_actions": actions,
                "inspection_targets": response.get("inspection_targets", []),
            },
            confidence=float(response.get("confidence_score", 0.75)),
            detail=detail,
        )


def build_default_skills() -> list[BaseSkill]:
    return [
        SignalMonitorSkill(),
        TraceInvestigationSkill(),
        ArtifactAnalysisSkill(),
        ComponentCorrelationSkill(),
        HypothesisGenerationSkill(),
        EvidenceReviewSkill(),
        ActionPlanningSkill(),
    ]
