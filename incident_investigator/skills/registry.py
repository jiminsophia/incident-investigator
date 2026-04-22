from __future__ import annotations

from incident_investigator.skills.base import BaseSkill


class SkillRegistry:
    def __init__(self, skills: list[BaseSkill]) -> None:
        self._skills = {skill.spec.name: skill for skill in skills}

    def get(self, name: str) -> BaseSkill:
        return self._skills[name]

    def names(self) -> list[str]:
        return list(self._skills)
