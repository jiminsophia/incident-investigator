from __future__ import annotations

from incident_investigator.planning.planner import PlanStep
from incident_investigator.planning.state import ExecutionState
from incident_investigator.skills.base import BaseSkill, SkillResult


class ResultValidator:
    def validate(
        self,
        step: PlanStep,
        skill: BaseSkill,
        result: SkillResult,
        state: ExecutionState,
    ) -> tuple[bool, str]:
        missing = [
            key for key in skill.spec.produced_keys if key not in result.findings
        ]
        if missing:
            return False, f"Missing expected fields: {', '.join(missing)}."

        if step.skill_name == "Focus Window Refinement":
            focused_window = result.findings["focused_window"]
            if not focused_window.get("start") or not focused_window.get("end"):
                return False, "Focused window refinement did not produce a usable incident window."

        if step.skill_name == "Trace Investigation":
            trace_summary = result.findings["trace_summary"]
            if state.context.get("anomalies") and trace_summary["slow_trace_count"] == 0:
                if state.failure_count(step.skill_name) < skill.spec.max_retries:
                    return False, "Not enough slow traces yet; retrying after other evidence is gathered."

        if step.skill_name == "Hypothesis Generation" and not result.findings["hypotheses"]:
            return False, "No hypotheses were generated."

        return True, ""
