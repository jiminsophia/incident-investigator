from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from incident_investigator.execution import SkillExecutor
from incident_investigator.llm.client import LLMClient
from incident_investigator.llm.prompts import (
    build_agentic_system_prompt,
    build_agentic_user_prompt,
)
from incident_investigator.planning.planner import PlanStep
from incident_investigator.planning.state import ExecutionState
from incident_investigator.planning.validator import ResultValidator
from incident_investigator.skills.base import SkillResult
from incident_investigator.skills.registry import SkillRegistry


@dataclass(frozen=True)
class ToolBinding:
    tool_name: str
    skill_name: str | None
    description: str


class ToolCallingInvestigator:
    def __init__(
        self,
        llm_client: LLMClient,
        registry: SkillRegistry,
        validator: ResultValidator,
        skill_executor: SkillExecutor,
        max_turns: int = 10,
    ) -> None:
        self.llm_client = llm_client
        self.registry = registry
        self.validator = validator
        self.skill_executor = skill_executor
        self.max_turns = max_turns
        self._bindings = [
            ToolBinding(
                tool_name="get_investigation_state",
                skill_name=None,
                description="Read the current investigation state, known findings, evidence gaps, and retry counts.",
            ),
            ToolBinding(
                tool_name="run_signal_monitor",
                skill_name="Signal Monitor",
                description="Skill: summarize metrics, logs, and user behavior, then detect anomalies.",
            ),
            ToolBinding(
                tool_name="run_trace_investigation",
                skill_name="Trace Investigation",
                description="Skill: inspect traces to narrow the primary incident window and hot services.",
            ),
            ToolBinding(
                tool_name="run_artifact_analysis",
                skill_name="Artifact Analysis",
                description="Skill: rank code/config artifacts related to the suspected incident path.",
            ),
            ToolBinding(
                tool_name="run_component_correlation",
                skill_name="Component Correlation",
                description="Skill: correlate suspicious components across gathered evidence.",
            ),
            ToolBinding(
                tool_name="run_evidence_review",
                skill_name="Evidence Review",
                description="Skill: evaluate evidence strength and identify remaining gaps.",
            ),
        ]

    def investigate(self, state: ExecutionState) -> dict[str, Any] | None:
        state.emit(
            "llm_mode",
            "LLM Investigator",
            "Using vLLM tool-calling mode for planning, skill selection, and final synthesis.",
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_agentic_system_prompt()},
            {"role": "user", "content": build_agentic_user_prompt(state.bundle)},
        ]

        tool_call_count = 0
        for turn in range(self.max_turns):
            state.emit(
                "llm_turn",
                "LLM Turn",
                f"Starting reasoning turn {turn + 1} of {self.max_turns}.",
            )
            try:
                response = self.llm_client.complete_with_tools(
                    messages,
                    self.tool_definitions(),
                    stream_handler=state.handle_llm_stream_event,
                    response_label=f"LLM Turn {turn + 1}",
                )
            except Exception as exc:
                state.trace.append(
                    {
                        "agent": "LLM Investigator",
                        "summary": "Tool-calling investigation unavailable",
                        "detail": (
                            "The LLM-led tool-calling path failed, so the coordinator will fall back "
                            f"to the deterministic planner.\n\nError: {exc}"
                        ),
                    }
                )
                state.emit(
                    "llm_fallback",
                    "LLM Investigator",
                    "Tool-calling failed, so the deterministic planner will take over.",
                    {"error": str(exc)},
                )
                return None
            messages.append(response["assistant_message"])
            tool_calls = response["tool_calls"]

            if not tool_calls:
                if tool_call_count == 0:
                    messages.append(
                        {
                            "role": "user",
                            "content": "You must investigate with tool calls before finalizing. Call the relevant skills first.",
                        }
                    )
                    continue

                report = self._parse_final_report(response["content"])
                if report is not None:
                    llm_summary = report.pop("llm_summary", "")
                    if llm_summary:
                        state.trace.append(
                            {
                                "agent": "LLM Investigator",
                                "summary": "Final report synthesized",
                                "detail": llm_summary,
                            }
                        )
                        state.emit(
                            "llm_summary",
                            "LLM Investigator",
                            llm_summary,
                        )
                    return report

                messages.append(
                    {
                        "role": "user",
                        "content": "Return only valid JSON matching the requested report schema.",
                    }
                )
                continue

            for tool_call in tool_calls:
                tool_call_count += 1
                state.emit(
                    "tool_call",
                    tool_call["name"],
                    tool_call["arguments"].get("reason", "LLM-selected tool call."),
                )
                result = self.execute_tool_call(tool_call, state)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": json.dumps(result),
                    }
                )

        return None

    def tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": binding.tool_name,
                    "description": binding.description,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reason": {
                                "type": "string",
                                "description": "Why this tool or skill is being called at this point in the investigation.",
                            }
                        },
                    },
                },
            }
            for binding in self._bindings
        ]

    def execute_tool_call(
        self, tool_call: dict[str, Any], state: ExecutionState
    ) -> dict[str, Any]:
        binding = next(
            binding for binding in self._bindings if binding.tool_name == tool_call["name"]
        )
        reason = tool_call["arguments"].get("reason", "LLM-selected tool call.")
        state.note(reason)

        if binding.skill_name is None:
            snapshot = self._state_snapshot(state)
            state.emit(
                "state_snapshot",
                "Investigation State",
                "Shared the latest investigation state with the LLM.",
                snapshot,
            )
            return snapshot

        skill = self.registry.get(binding.skill_name)
        try:
            result = self.skill_executor.execute(skill, state.context)
        except Exception as exc:
            result = SkillResult(
                skill=binding.skill_name,
                success=False,
                summary=f"{binding.skill_name} execution failed",
                detail=f"Execution error: {exc}",
                errors=[str(exc)],
            )
            state.record_failure(result, f"Execution error: {exc}")
            return {
                "success": False,
                "skill": binding.skill_name,
                "summary": result.summary,
                "errors": result.errors,
                "known_context": self._state_snapshot(state),
            }

        is_valid, validation_reason = self.validator.validate(
            PlanStep(skill_name=binding.skill_name, reason=reason),
            skill,
            result,
            state,
        )
        if is_valid:
            state.record_success(result)
            return {
                "success": True,
                "skill": binding.skill_name,
                "summary": result.summary,
                "confidence": result.confidence,
                "findings": result.findings,
                "known_context": self._state_snapshot(state),
            }

        state.record_failure(result, validation_reason)
        return {
            "success": False,
            "skill": binding.skill_name,
            "summary": result.summary,
            "confidence": result.confidence,
            "errors": result.errors + [validation_reason],
            "findings": result.findings,
            "known_context": self._state_snapshot(state),
        }

    def _state_snapshot(self, state: ExecutionState) -> dict[str, Any]:
        keys_of_interest = [
            "metric_summary",
            "log_summary",
            "user_summary",
            "anomalies",
            "trace_summary",
            "relevant_artifacts",
            "suspicious_components",
            "primary_window",
            "investigation_confidence",
            "evidence_gaps",
            "hypotheses",
            "recommended_actions",
            "inspection_targets",
        ]
        return {
            "known_fields": {
                key: state.context[key]
                for key in keys_of_interest
                if key in state.context
            },
            "failed_attempts": dict(state.failed_attempts),
            "recent_planning_notes": state.planning_notes[-5:],
        }

    def _parse_final_report(self, content: str) -> dict[str, Any] | None:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None
