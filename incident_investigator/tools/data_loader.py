from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path


def _load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_scenario_bundle(data_root: Path, scenario_key: str) -> dict:
    scenario_root = data_root / scenario_key
    bundle = {
        "metadata": _load_json(scenario_root / "metadata.json"),
        "logs": _load_json(scenario_root / "logs.json"),
        "metrics": _load_json(scenario_root / "metrics.json"),
        "traces": _load_json(scenario_root / "traces.json"),
        "user_events": _load_json(scenario_root / "user_events.json"),
        "artifacts": _load_json(scenario_root / "artifacts.json"),
    }
    timeline_path = scenario_root / "timeline.json"
    if timeline_path.exists():
        bundle["timeline"] = _load_json(timeline_path)
    return bundle


def build_replay_bundle(bundle: dict, stage_index: int) -> dict:
    timeline = bundle.get("timeline", [])
    if not timeline:
        return bundle

    stage = timeline[max(0, min(stage_index, len(timeline) - 1))]
    replay_bundle = deepcopy(bundle)
    replay_bundle["metadata"] = {
        **bundle["metadata"],
        "summary": stage["summary"],
    }
    replay_bundle["logs"] = bundle["logs"][: stage["log_count"]]
    replay_bundle["traces"] = bundle["traces"][: stage["trace_count"]]
    replay_bundle["user_events"] = stage["user_events"]
    replay_bundle["metrics"] = stage["metrics"]
    replay_bundle["replay_stage"] = stage
    return replay_bundle
