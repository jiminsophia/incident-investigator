from __future__ import annotations

from collections import Counter

from incident_investigator.llm.prompts import build_action_prompt, build_hypothesis_prompt
from incident_investigator.skills.base import BaseSkill, SkillResult, SkillSpec
from incident_investigator.tools.anomaly_detector import detect_anomalies
from incident_investigator.tools.config_retriever import retrieve_relevant_artifacts
from incident_investigator.tools.event_processing import (
    calculate_incident_severity as calculate_event_severity,
    derive_log_records,
    derive_service_metrics,
    derive_user_journeys,
    select_focus_window,
    summarize_request_paths,
)
from incident_investigator.tools.log_parser import summarize_logs
from incident_investigator.tools.metrics import summarize_metrics
from incident_investigator.tools.observability import reduce_observability
from incident_investigator.tools.reporting import format_agent_detail
from incident_investigator.tools.severity import calculate_incident_severity
from incident_investigator.tools.traces import summarize_traces
from incident_investigator.tools.user_behavior import summarize_user_behavior


def _active_metric_summary(context: dict) -> dict:
    return context.get("focused_metric_summary", context.get("metric_summary", {}))


def _active_log_summary(context: dict) -> dict:
    return context.get("focused_log_summary", context.get("log_summary", {}))


def _active_user_summary(context: dict) -> dict:
    return context.get("focused_user_summary", context.get("user_summary", {}))


def _active_request_path_summary(context: dict) -> dict:
    return context.get("focused_request_path_summary", context.get("request_path_summary", {}))


def _active_severity_summary(context: dict) -> dict:
    return context.get("focused_severity_summary", context.get("severity_summary", {}))


class ObservabilityReductionSkill(BaseSkill):
    spec = SkillSpec(
        name="Observability Reduction",
        description="Reduce rough raw events into service metrics, derived logs, and user-journey summaries.",
        required_keys=("raw_events", "baseline_events", "filters"),
        produced_keys=(
            "observability_reduced",
            "logs",
            "metrics",
            "user_events",
            "reduction_summary",
            "request_path_summary",
            "severity_summary",
            "incident_score",
            "incident_severity",
            "severity_hint",
        ),
    )

    def run(self, context: dict) -> SkillResult:
        reduced = reduce_observability(
            context["raw_events"],
            context["filters"],
            baseline_events=context.get("baseline_events", []),
        )
        detail = format_agent_detail(
            "Reduce raw observability events",
            [
                f"Reduced {len(context['raw_events'])} in-window events against {len(context.get('baseline_events', []))} baseline events.",
                f"Derived {len(reduced['metrics'])} service metrics, {len(reduced['logs'])} log records, and {len(reduced['user_events'])} journey summaries.",
                reduced["request_path_summary"]["path_summary"],
                reduced["severity_summary"]["summary"],
            ],
        )
        return SkillResult(
            skill=self.spec.name,
            success=True,
            summary="Raw events reduced into investigation signals",
            findings={
                **reduced,
                "observability_reduced": True,
            },
            confidence=0.86,
            detail=detail,
        )


class SignalMonitorSkill(BaseSkill):
    spec = SkillSpec(
        name="Signal Monitor",
        description="Summarize derived observability signals and detect anomalies.",
        required_keys=("metrics", "logs", "user_events", "severity_summary"),
        produced_keys=("metric_summary", "log_summary", "user_summary", "anomalies"),
    )

    def run(self, context: dict) -> SkillResult:
        metric_summary = summarize_metrics(context["metrics"])
        log_summary = summarize_logs(context["logs"])
        user_summary = summarize_user_behavior(context["user_events"])
        severity = calculate_incident_severity(metric_summary, log_summary, user_summary)
        merged_severity = {
            **context["severity_summary"],
            "incident_score": severity["incident_score"],
            "severity": severity["incident_severity"],
            "severity_hint": severity["severity_hint"],
            "summary": severity["summary"],
        }
        anomalies = detect_anomalies(metric_summary, log_summary, user_summary, merged_severity)

        confidence = min(0.95, 0.35 + (severity["incident_score"] / 100))
        detail = format_agent_detail(
            "Detect operational anomalies",
            [
                f"Detected {len(anomalies)} anomalies across metrics, logs, and user signals.",
                f"Peak latency service: {metric_summary['highest_latency_service']}.",
                f"Error hotspot: {log_summary['top_error_component']}.",
                f"User impact: {user_summary['dropoff_summary']}",
                f"Severity now computes to {merged_severity['severity']} with score {merged_severity['incident_score']}.",
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
                "severity_summary": merged_severity,
                "incident_score": merged_severity["incident_score"],
                "incident_severity": merged_severity["severity"],
                "severity_hint": merged_severity["severity_hint"],
                "anomalies": anomalies,
            },
            confidence=confidence,
            detail=detail,
        )


class FocusWindowRefinementSkill(BaseSkill):
    spec = SkillSpec(
        name="Focus Window Refinement",
        description="Pick the most incident-dense time slice and recompute focused summaries for it.",
        required_keys=("raw_events", "baseline_events"),
        produced_keys=(
            "focused_window",
            "focused_logs",
            "focused_metrics",
            "focused_user_events",
            "focused_metric_summary",
            "focused_log_summary",
            "focused_user_summary",
            "focused_request_path_summary",
            "focused_severity_summary",
        ),
    )

    def run(self, context: dict) -> SkillResult:
        focused_window = select_focus_window(
            context["raw_events"],
            context.get("baseline_events", []),
        )
        focused_events = focused_window["events"]
        focused_metrics = derive_service_metrics(focused_events, context.get("baseline_events", []))
        focused_logs = derive_log_records(focused_events, context.get("baseline_events", []))
        focused_user_events = derive_user_journeys(focused_events, context.get("baseline_events", []))
        focused_metric_summary = summarize_metrics(focused_metrics)
        focused_log_summary = summarize_logs(focused_logs)
        focused_user_summary = summarize_user_behavior(focused_user_events)
        focused_request_path_summary = summarize_request_paths(focused_events)
        focused_severity_summary = calculate_event_severity(
            focused_metrics,
            focused_user_events,
            focused_logs,
        )

        confidence = 0.25 if not focused_events else min(0.9, 0.4 + (focused_window["incident_score"] / 120))
        detail = format_agent_detail(
            "Refine the incident focus window",
            [
                f"Selected focused window {focused_window['label']} with incident score {focused_window['incident_score']}.",
                f"Focused event count: {len(focused_events)}.",
                focused_request_path_summary["path_summary"],
                focused_severity_summary["summary"],
            ],
        )
        return SkillResult(
            skill=self.spec.name,
            success=True,
            summary="Focused window recomputed",
            findings={
                "focused_window": {
                    key: value
                    for key, value in focused_window.items()
                    if key != "events"
                },
                "focused_logs": focused_logs,
                "focused_metrics": focused_metrics,
                "focused_user_events": focused_user_events,
                "focused_metric_summary": focused_metric_summary,
                "focused_log_summary": focused_log_summary,
                "focused_user_summary": focused_user_summary,
                "focused_request_path_summary": focused_request_path_summary,
                "focused_severity_summary": focused_severity_summary,
            },
            confidence=confidence,
            detail=detail,
        )


class TraceInvestigationSkill(BaseSkill):
    spec = SkillSpec(
        name="Trace Investigation",
        description="Inspect slow traces to identify the primary incident window and hot services.",
        required_keys=("traces",),
        produced_keys=("trace_summary",),
        max_retries=2,
    )

    def run(self, context: dict) -> SkillResult:
        focused_window = context.get("focused_window", {})
        trace_summary = summarize_traces(
            context["traces"],
            start=focused_window.get("start"),
            end=focused_window.get("end"),
        )
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
        metric_summary = _active_metric_summary(context)
        log_summary = _active_log_summary(context)
        relevant_artifacts = retrieve_relevant_artifacts(
            context["artifacts"],
            log_summary.get("top_error_component", "unknown"),
            metric_summary.get("highest_latency_service", "unknown"),
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
        description="Correlate suspicious components across reduced signals and traces.",
        required_keys=("metric_summary", "log_summary"),
        produced_keys=("suspicious_components", "primary_window"),
    )

    def run(self, context: dict) -> SkillResult:
        trace_summary = context.get(
            "trace_summary",
            {"hot_services": [], "primary_window": "not enough trace data yet"},
        )
        metric_summary = _active_metric_summary(context)
        log_summary = _active_log_summary(context)
        request_path_summary = _active_request_path_summary(context)
        suspicious_components = [
            log_summary.get("top_error_component"),
            metric_summary.get("highest_latency_service"),
            metric_summary.get("highest_error_service"),
            *trace_summary["hot_services"],
        ]
        component_counts = Counter(component for component in suspicious_components if component)
        primary_window = trace_summary["primary_window"]
        if primary_window == "not enough trace data yet":
            primary_window = context.get("focused_window", {}).get("label", primary_window)
        findings = {
            "suspicious_components": component_counts.most_common(4),
            "primary_window": primary_window,
            "failing_path": request_path_summary.get("failing_path", "unknown"),
        }
        confidence = 0.25 if not findings["suspicious_components"] else 0.7
        detail = format_agent_detail(
            "Correlate evidence across modules",
            [
                f"Focused on incident window {primary_window}.",
                f"Request path under pressure: {request_path_summary.get('failing_path', 'unknown')}.",
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

        metric_summary = _active_metric_summary(context)
        log_summary = _active_log_summary(context)
        user_summary = _active_user_summary(context)
        request_path_summary = _active_request_path_summary(context)
        severity_summary = _active_severity_summary(context)
        anomalies = context["anomalies"]
        trace_summary = context.get(
            "trace_summary",
            {
                "trace_summary": "Trace evidence is still thin.",
                "primary_window": context.get("focused_window", {}).get("label", "not enough trace data yet"),
            },
        )
        relevant_artifacts = context.get("relevant_artifacts", [])
        top_error = log_summary.get("top_error_component", "unknown")
        top_latency = metric_summary.get("highest_latency_service", "unknown")
        artifact_titles = [item["title"] for item in relevant_artifacts]
        failing_path = request_path_summary.get("failing_path", "unknown")

        if not anomalies:
            hypotheses = [
                {
                    "title": "Insufficient evidence for a confirmed incident",
                    "confidence": "Low",
                    "rationale": (
                        "Latency, failures, and user impact remain too close to baseline to support a confident incident claim."
                    ),
                    "evidence": [
                        metric_summary.get("latency_summary", "No latency evidence available."),
                        log_summary.get("error_summary", "No log evidence available."),
                        user_summary.get("dropoff_summary", "No user impact visible yet."),
                    ],
                }
            ]
            confidence = 0.2
            detail_lines = [
                "Held off on a strong root-cause claim because the signal is still weak.",
                "Waiting for stronger alignment across latency, failures, traces, and user impact.",
            ]
        else:
            has_trace_support = bool(trace_summary.get("hot_services"))
            has_artifact_support = bool(relevant_artifacts)
            hypotheses = [
                {
                    "title": f"{top_latency} dependency saturation caused cascading latency on {failing_path}",
                    "confidence": "High" if has_trace_support else "Medium",
                    "rationale": (
                        f"{top_latency} shows the highest latency spike, {top_error} dominates failures, "
                        f"and the degraded request path is {failing_path}."
                    ),
                    "evidence": [
                        metric_summary["latency_summary"],
                        trace_summary["trace_summary"],
                        severity_summary.get("summary", "Severity summary unavailable."),
                    ],
                },
                {
                    "title": f"{top_error} rollout or timeout policy change introduced request failures",
                    "confidence": "Medium" if has_artifact_support else "Low",
                    "rationale": (
                        f"{top_error} dominates the error logs and the retrieved artifacts align with the failing path "
                        f"{failing_path} during {trace_summary['primary_window']}."
                    ),
                    "evidence": [
                        log_summary["error_summary"],
                        f"Primary incident window: {context.get('primary_window', trace_summary['primary_window'])}",
                        f"Artifact matches: {', '.join(artifact_titles[:3]) or 'limited matches'}",
                    ],
                },
            ]
            confidence = 0.55 + (0.15 if has_trace_support else 0.0) + (0.1 if has_artifact_support else 0.0)
            detail_lines = [
                f"Ranked {len(hypotheses)} root-cause hypotheses.",
                f"Top hypothesis links {top_latency} latency with downstream timeout behavior on {failing_path}.",
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
            "Use only the provided evidence. Do not invent unavailable logs, traces, artifacts, or degraded paths."
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
        focused_window = context.get("focused_window", {})
        severity_summary = _active_severity_summary(context)

        evidence_gaps = []
        if not focused_window:
            evidence_gaps.append("Focused incident window has not been refined yet.")
        if trace_summary.get("slow_trace_count", 0) == 0:
            evidence_gaps.append("Trace evidence is still limited.")
        if not relevant_artifacts:
            evidence_gaps.append("Matched code/config artifacts are limited.")
        if hypotheses and hypotheses[0]["confidence"] == "Low":
            evidence_gaps.append("Top hypothesis confidence is still low.")
        if severity_summary.get("severity") == "Watch":
            evidence_gaps.append("Severity remains below incident-confirmation threshold.")

        investigation_confidence = max(0.2, 0.85 - 0.12 * len(evidence_gaps))
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
        request_path_summary = _active_request_path_summary(context)
        focused_window = context.get("focused_window", {})

        if hypotheses[0]["confidence"] == "Low":
            actions = [
                "Keep the incident in watch mode and continue collecting the next few minutes of raw events, traces, and journey outcomes.",
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
                f"Mitigate user impact first on {request_path_summary.get('primary_entry_point', 'the affected entry point')}: roll back the latest risky config or feature gate.",
                "Reduce pressure on the hot dependency with cache warming, connection pool checks, or temporary traffic shaping.",
                f"Inspect timeout, retry, and circuit-breaker settings for the incident window {focused_window.get('label', 'under review')}.",
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
        ObservabilityReductionSkill(),
        SignalMonitorSkill(),
        FocusWindowRefinementSkill(),
        TraceInvestigationSkill(),
        ArtifactAnalysisSkill(),
        ComponentCorrelationSkill(),
        HypothesisGenerationSkill(),
        EvidenceReviewSkill(),
        ActionPlanningSkill(),
    ]
