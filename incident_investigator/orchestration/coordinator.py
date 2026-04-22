from __future__ import annotations

from typing import Any, Callable

from incident_investigator.execution import build_skill_executor
from incident_investigator.llm import LLMClient, LLMConfig, ToolCallingInvestigator
from incident_investigator.planning import ExecutionState, InvestigationPlanner, ResultValidator
from incident_investigator.skills import SkillRegistry, build_default_skills


class CoordinatorAgent:
    def __init__(
        self,
        llm_config: LLMConfig | None = None,
        execution_backend: str = "native",
    ) -> None:
        self.registry = SkillRegistry(build_default_skills())
        self.planner = InvestigationPlanner()
        self.validator = ResultValidator()
        self.skill_executor = build_skill_executor(execution_backend)
        self.llm_client = LLMClient(llm_config) if llm_config else None
        self.tool_calling_investigator = (
            ToolCallingInvestigator(
                llm_client=self.llm_client,
                registry=self.registry,
                validator=self.validator,
                skill_executor=self.skill_executor,
            )
            if self.llm_client is not None
            else None
        )

    def run(
        self,
        bundle: dict,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict:
        enriched_bundle = dict(bundle)
        if self.llm_client is not None:
            enriched_bundle["llm_client"] = self.llm_client
        state = ExecutionState(enriched_bundle, event_callback=event_callback)
        state.context["llm_stream_callback"] = state.handle_llm_stream_event
        state.emit(
            "run_started",
            "Coordinator",
            "Investigation started.",
            {
                "llm_enabled": self.llm_client is not None,
                "execution_backend": self.skill_executor.backend_name,
                "scenario": bundle["metadata"]["title"],
            },
        )
        state.emit(
            "execution_backend",
            self.skill_executor.display_name,
            f"Skill execution is running through the {self.skill_executor.display_name} backend.",
            {"backend": self.skill_executor.backend_name},
        )

        if self.tool_calling_investigator is not None:
            report = self.tool_calling_investigator.investigate(state)
            if report is not None:
                final_report = self._finalize_report(report, state)
                state.emit("run_completed", "Coordinator", "Investigation completed.")
                return final_report

        for _ in range(12):
            step = self.planner.choose_next_step(state, self.registry)
            if step is None:
                break

            state.note(step.reason)
            state.emit(
                "planned_step",
                step.skill_name,
                step.reason,
            )
            skill = self.registry.get(step.skill_name)
            result = self.skill_executor.execute(skill, state.context)
            is_valid, reason = self.validator.validate(step, skill, result, state)
            if is_valid:
                state.record_success(result)
            else:
                state.record_failure(result, reason)

        final_report = self._finalize_report(self._build_final_report(state), state)
        state.emit("run_completed", "Coordinator", "Investigation completed.")
        return final_report

    def _build_final_report(self, state: ExecutionState) -> dict:
        metadata = state.context["metadata"]
        anomalies = state.context.get("anomalies", [])
        hypotheses = state.context.get(
            "hypotheses",
            [
                {
                    "title": "Investigation did not complete",
                    "confidence": "Low",
                    "rationale": "The planning loop ran out of steps before producing a root-cause hypothesis.",
                    "evidence": [],
                }
            ],
        )
        metric_summary = state.context.get(
            "metric_summary",
            {"highest_latency_service": "unknown", "latency_summary": "No latency metrics available yet."},
        )
        primary_window = state.context.get("primary_window") or state.context.get(
            "trace_summary", {}
        ).get("primary_window", "unknown")
        supporting_evidence = [anomaly["description"] for anomaly in anomalies]
        supporting_evidence.extend(hypotheses[0].get("evidence", []))
        supporting_evidence.extend(state.context.get("evidence_gaps", []))

        return {
            "anomaly_summary": {
                "headline": metadata["title"],
                "summary": metadata["summary"],
                "severity": metadata["severity"],
                "impacted_service": metric_summary["highest_latency_service"],
                "time_window": primary_window,
            },
            "root_causes": hypotheses,
            "recommended_actions": state.context.get("recommended_actions", []),
            "supporting_evidence": supporting_evidence,
            "inspection_targets": state.context.get("inspection_targets", []),
            "agent_trace": state.trace,
        }

    def _finalize_report(self, report: dict, state: ExecutionState) -> dict:
        anomaly_summary = report.setdefault("anomaly_summary", {})
        metadata = state.context["metadata"]
        metric_summary = state.context.get(
            "metric_summary",
            {"highest_latency_service": "unknown"},
        )
        primary_window = state.context.get("primary_window") or state.context.get(
            "trace_summary", {}
        ).get("primary_window", "unknown")

        anomaly_summary.setdefault("headline", metadata["title"])
        anomaly_summary.setdefault("summary", metadata["summary"])
        anomaly_summary.setdefault("severity", metadata["severity"])
        anomaly_summary.setdefault("impacted_service", metric_summary["highest_latency_service"])
        anomaly_summary.setdefault("time_window", primary_window)

        report.setdefault("root_causes", [])
        report.setdefault("recommended_actions", [])
        report.setdefault("supporting_evidence", [])
        report.setdefault("inspection_targets", state.context.get("inspection_targets", []))
        report["agent_trace"] = state.trace
        return report
