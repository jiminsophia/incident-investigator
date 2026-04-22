from __future__ import annotations

from dataclasses import dataclass

from incident_investigator.planning.state import ExecutionState
from incident_investigator.skills.registry import SkillRegistry


@dataclass(frozen=True)
class PlanStep:
    skill_name: str
    reason: str


class InvestigationPlanner:
    def choose_next_step(
        self, state: ExecutionState, registry: SkillRegistry
    ) -> PlanStep | None:
        if not state.has("observability_reduced"):
            return PlanStep(
                skill_name="Observability Reduction",
                reason="We need to derive logs, metrics, traces, and journey summaries from raw events before deeper investigation.",
            )

        if not state.has("anomalies"):
            return PlanStep(
                skill_name="Signal Monitor",
                reason="We need a baseline read across metrics, logs, and user impact before planning deeper steps.",
            )

        if not state.has("focused_window"):
            return PlanStep(
                skill_name="Focus Window Refinement",
                reason="We should narrow the investigation to the most incident-dense raw-event window before tracing deeper.",
            )

        if not state.has("trace_summary") and state.failure_count("Trace Investigation") < (
            registry.get("Trace Investigation").spec.max_retries + 1
        ):
            return PlanStep(
                skill_name="Trace Investigation",
                reason="Trace evidence can narrow the primary window and identify hot services.",
            )

        if not state.has("relevant_artifacts"):
            return PlanStep(
                skill_name="Artifact Analysis",
                reason="Artifact matches help us validate whether the incident lines up with recent config or code changes.",
            )

        if not state.has("suspicious_components", "primary_window"):
            return PlanStep(
                skill_name="Component Correlation",
                reason="We should correlate the strongest signals into a ranked list of suspicious components.",
            )

        if not state.has("hypotheses"):
            return PlanStep(
                skill_name="Hypothesis Generation",
                reason="There is enough evidence to generate root-cause hypotheses.",
            )

        if not state.has("investigation_confidence"):
            return PlanStep(
                skill_name="Evidence Review",
                reason="We should review evidence quality before finalizing actions.",
            )

        if not state.has("recommended_actions"):
            return PlanStep(
                skill_name="Action Planning",
                reason="The system has enough context to prepare mitigation and follow-up actions.",
            )

        return None
