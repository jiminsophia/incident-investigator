from incident_investigator.skills.registry import SkillRegistry


def build_default_skills():
    from incident_investigator.skills.modules import build_default_skills as _build_default_skills

    return _build_default_skills()


__all__ = ["SkillRegistry", "build_default_skills"]
