from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SkillSpec:
    name: str
    description: str
    required_keys: tuple[str, ...]
    produced_keys: tuple[str, ...]
    max_retries: int = 1


@dataclass
class SkillResult:
    skill: str
    success: bool
    summary: str
    findings: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    detail: str = ""
    errors: list[str] = field(default_factory=list)

    def trace_item(self, attempt: int) -> dict[str, str]:
        return {
            "agent": self.skill,
            "summary": self.summary,
            "detail": "\n".join(
                [
                    f"Attempt: {attempt}",
                    f"Status: {'success' if self.success else 'failed'}",
                    f"Confidence: {self.confidence:.2f}",
                    "",
                    self.detail or "No additional detail recorded.",
                ]
            ),
        }


class BaseSkill:
    spec: SkillSpec

    def run(self, context: dict[str, Any]) -> SkillResult:
        raise NotImplementedError
