from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentOutput:
    agent: str
    summary: str
    findings: dict[str, Any] = field(default_factory=dict)
    detail: str = ""


class BaseAgent:
    name = "BaseAgent"
    role = "Generic"

    def run(self, context: dict[str, Any]) -> AgentOutput:
        raise NotImplementedError

