from __future__ import annotations

from incident_investigator.agents.base import AgentOutput
from incident_investigator.agents.roles import (
    ActionAgent,
    InvestigatorAgent,
    MonitorAgent,
    RootCauseAgent,
)
from incident_investigator.tools.reporting import build_final_report


class CoordinatorAgent:
    def __init__(self) -> None:
        self.monitor = MonitorAgent()
        self.investigator = InvestigatorAgent()
        self.root_cause = RootCauseAgent()
        self.action = ActionAgent()

    def run(self, bundle: dict) -> dict:
        monitor_output = self.monitor.run(bundle)
        investigator_output = self.investigator.run(
            {
                **bundle,
                "monitor": monitor_output.findings,
            }
        )
        root_cause_output = self.root_cause.run(
            {
                **bundle,
                "monitor": monitor_output.findings,
                "investigator": investigator_output.findings,
            }
        )
        action_output = self.action.run(
            {
                **bundle,
                "monitor": monitor_output.findings,
                "investigator": investigator_output.findings,
                "root_cause": root_cause_output.findings,
            }
        )

        outputs = [
            monitor_output,
            investigator_output,
            root_cause_output,
            action_output,
        ]
        return build_final_report(bundle["metadata"], outputs)

