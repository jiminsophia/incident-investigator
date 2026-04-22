from __future__ import annotations

import unittest

from incident_investigator.execution import (
    DirectSkillExecutor,
    get_execution_backend_status,
    skill_result_from_payload,
    skill_result_to_payload,
)
from incident_investigator.skills.base import BaseSkill, SkillResult, SkillSpec


class _ExampleSkill(BaseSkill):
    spec = SkillSpec(
        name="Example Skill",
        description="Example",
        required_keys=(),
        produced_keys=("answer",),
    )

    def run(self, context: dict) -> SkillResult:
        return SkillResult(
            skill=self.spec.name,
            success=True,
            summary="Example finished",
            findings={"answer": context["value"]},
            confidence=0.5,
            detail="Worked as expected.",
        )


class ExecutionHelpersTests(unittest.TestCase):
    def test_direct_executor_runs_skill(self) -> None:
        executor = DirectSkillExecutor()
        result = executor.execute(_ExampleSkill(), {"value": 7})
        self.assertEqual(result.findings, {"answer": 7})

    def test_skill_result_round_trip(self) -> None:
        original = SkillResult(
            skill="Example Skill",
            success=True,
            summary="Done",
            findings={"root_cause": "redis"},
            confidence=0.8,
            detail="Details",
            errors=["minor"],
        )

        payload = skill_result_to_payload(original)
        recovered = skill_result_from_payload(payload, "Fallback")

        self.assertEqual(recovered.skill, original.skill)
        self.assertEqual(recovered.summary, original.summary)
        self.assertEqual(recovered.findings, original.findings)
        self.assertEqual(recovered.errors, original.errors)

    def test_native_backend_status_is_available(self) -> None:
        status = get_execution_backend_status("native")
        self.assertTrue(status.available)
        self.assertEqual(status.name, "native")


if __name__ == "__main__":
    unittest.main()
