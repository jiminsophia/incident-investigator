from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from incident_investigator.skills.base import SkillResult


@dataclass
class ExecutionState:
    bundle: dict[str, Any]
    event_callback: Callable[[dict[str, Any]], None] | None = None
    context: dict[str, Any] = field(init=False)
    completed: dict[str, SkillResult] = field(default_factory=dict)
    failed_attempts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    trace: list[dict[str, str]] = field(default_factory=list)
    planning_notes: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.context = dict(self.bundle)

    def has(self, *keys: str) -> bool:
        return all(key in self.context for key in keys)

    def failure_count(self, skill_name: str) -> int:
        return self.failed_attempts[skill_name]

    def record_success(self, result: SkillResult) -> None:
        self.context.update(result.findings)
        self.completed[result.skill] = result
        attempt = self.failed_attempts[result.skill] + 1
        self.trace.append(result.trace_item(attempt))
        self.emit(
            "skill_success",
            result.skill,
            result.summary,
            {
                "attempt": attempt,
                "confidence": result.confidence,
                "findings": result.findings,
            },
        )

    def record_failure(self, result: SkillResult, reason: str) -> None:
        self.failed_attempts[result.skill] += 1
        errors = list(result.errors)
        errors.append(reason)
        failed_result = SkillResult(
            skill=result.skill,
            success=False,
            summary=f"{result.summary} - retrying",
            findings=result.findings,
            confidence=result.confidence,
            detail="\n".join(filter(None, [result.detail, "", "Failure reason:", reason])),
            errors=errors,
        )
        self.trace.append(failed_result.trace_item(self.failed_attempts[result.skill]))
        self.emit(
            "skill_failure",
            result.skill,
            reason,
            {
                "attempt": self.failed_attempts[result.skill],
                "errors": errors,
                "findings": result.findings,
            },
        )

    def note(self, message: str) -> None:
        self.planning_notes.append(message)
        self.emit("note", "Planner", message)

    def emit(
        self,
        kind: str,
        title: str,
        detail: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        event = {
            "kind": kind,
            "title": title,
            "detail": detail,
            "payload": payload or {},
            "transient": False,
        }
        self.events.append(event)
        if self.event_callback is not None:
            self.event_callback(event)

    def emit_transient(
        self,
        kind: str,
        title: str,
        detail: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        event = {
            "kind": kind,
            "title": title,
            "detail": detail,
            "payload": payload or {},
            "transient": True,
        }
        if self.event_callback is not None:
            self.event_callback(event)

    def handle_llm_stream_event(self, event: dict[str, Any]) -> None:
        payload = {
            "stream_id": event["stream_id"],
            "label": event["label"],
            "category": event.get("category", "llm"),
        }
        phase = event["phase"]
        if phase == "start":
            self.emit_transient(
                "llm_response_start",
                event["label"],
                f"Started streaming {event['label'].lower()}.",
                payload,
            )
            return

        if phase == "delta":
            payload["delta"] = event.get("delta", "")
            self.emit_transient(
                "llm_response_delta",
                event["label"],
                f"Streaming {event['label'].lower()}.",
                payload,
            )
            return

        if phase == "complete":
            payload["content"] = event.get("content", "")
            self.emit_transient(
                "llm_response_end",
                event["label"],
                f"Completed streaming {event['label'].lower()}.",
                payload,
            )
