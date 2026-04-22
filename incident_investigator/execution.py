from __future__ import annotations

import asyncio
import importlib
import re
from dataclasses import dataclass
from typing import Any

from incident_investigator.skills.base import BaseSkill, SkillResult


@dataclass(frozen=True)
class ExecutionBackendStatus:
    name: str
    available: bool
    detail: str


class SkillExecutor:
    backend_name = "native"
    display_name = "Native Python"

    def execute(self, skill: BaseSkill, context: dict[str, Any]) -> SkillResult:
        raise NotImplementedError


class DirectSkillExecutor(SkillExecutor):
    backend_name = "native"
    display_name = "Native Python"

    def execute(self, skill: BaseSkill, context: dict[str, Any]) -> SkillResult:
        return skill.run(context)


def skill_result_to_payload(result: SkillResult) -> dict[str, Any]:
    return {
        "skill": result.skill,
        "success": result.success,
        "summary": result.summary,
        "findings": result.findings,
        "confidence": result.confidence,
        "detail": result.detail,
        "errors": result.errors,
    }


def skill_result_from_payload(payload: Any, fallback_skill_name: str) -> SkillResult:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected NAT function payload to be a dict, received {type(payload)!r}.")

    return SkillResult(
        skill=payload.get("skill", fallback_skill_name),
        success=bool(payload.get("success", False)),
        summary=payload.get("summary", f"{fallback_skill_name} completed"),
        findings=dict(payload.get("findings", {})),
        confidence=float(payload.get("confidence", 0.0)),
        detail=payload.get("detail", ""),
        errors=list(payload.get("errors", [])),
    )


def get_execution_backend_status(name: str) -> ExecutionBackendStatus:
    if name == "native":
        return ExecutionBackendStatus(
            name="native",
            available=True,
            detail="Uses the built-in Python skill executor.",
        )

    if name == "nemo_nat":
        if importlib.util.find_spec("nat") is None:
            return ExecutionBackendStatus(
                name="nemo_nat",
                available=False,
                detail="Install the `nvidia-nat` package to enable NeMo Agent Toolkit execution.",
            )
        return ExecutionBackendStatus(
            name="nemo_nat",
            available=True,
            detail="Executes each investigation skill through a NeMo Agent Toolkit LambdaFunction wrapper.",
        )

    return ExecutionBackendStatus(
        name=name,
        available=False,
        detail=f"Unknown execution backend: {name}",
    )


def build_skill_executor(name: str) -> SkillExecutor:
    if name == "native":
        return DirectSkillExecutor()
    if name == "nemo_nat":
        status = get_execution_backend_status(name)
        if not status.available:
            raise RuntimeError(status.detail)
        return NemoNATSkillExecutor()
    raise ValueError(f"Unsupported execution backend: {name}")


class NemoNATSkillExecutor(SkillExecutor):
    backend_name = "nemo_nat"
    display_name = "NeMo Agent Toolkit"

    def __init__(self) -> None:
        from nat.builder.function import LambdaFunction
        from nat.builder.function_info import FunctionInfo
        from nat.data_models.function import EmptyFunctionConfig

        self._lambda_function_cls = LambdaFunction
        self._function_info_cls = FunctionInfo
        self._empty_function_config_cls = EmptyFunctionConfig
        self._function_cache: dict[str, Any] = {}

    def execute(self, skill: BaseSkill, context: dict[str, Any]) -> SkillResult:
        nat_function = self._function_cache.get(skill.spec.name)
        if nat_function is None:
            nat_function = self._build_nat_function(skill)
            self._function_cache[skill.spec.name] = nat_function

        payload = asyncio.run(nat_function.ainvoke(context))
        return skill_result_from_payload(payload, skill.spec.name)

    def _build_nat_function(self, skill: BaseSkill) -> Any:
        async def invoke(skill_context: dict[str, object]) -> dict[str, object]:
            return skill_result_to_payload(skill.run(skill_context))

        info = self._function_info_cls.from_fn(
            invoke,
            description=skill.spec.description,
        )
        config = self._empty_function_config_cls(name=skill.spec.name)
        return self._lambda_function_cls.from_info(
            config=config,
            info=info,
            instance_name=self._instance_name(skill.spec.name),
        )

    def _instance_name(self, skill_name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", skill_name.lower()).strip("_")
