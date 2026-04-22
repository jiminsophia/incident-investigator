from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from incident_investigator.tools.log_parser import summarize_logs
from incident_investigator.tools.metrics import summarize_metrics
from incident_investigator.tools.observability import reduce_observability
from incident_investigator.tools.severity import calculate_incident_severity
from incident_investigator.tools.user_behavior import summarize_user_behavior


def _load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            normalized = line.strip()
            if normalized:
                records.append(json.loads(normalized))
    return records


def _merge_slice_filters(base: dict, override: dict | None) -> dict:
    merged = deepcopy(base)
    if override:
        merged.update(override)
    return merged


def _within_window(timestamp: str, start: str | None, end: str | None) -> bool:
    if start and timestamp < start:
        return False
    if end and timestamp > end:
        return False
    return True


def _format_window_label(start: str | None, end: str | None) -> str:
    if not start or not end:
        return "unknown"
    return f"{start[11:16]}-{end[11:16]} UTC"


def _slice_raw_events(
    raw_events: list[dict],
    *,
    start: str | None,
    end: str | None,
) -> list[dict]:
    return [
        event
        for event in raw_events
        if _within_window(event["timestamp"], start, end)
    ]


def _slice_artifacts(raw_artifacts: list[dict], filters: dict) -> list[dict]:
    domains = set(filters.get("artifact_domains", []))
    keywords = {keyword.lower() for keyword in filters.get("artifact_keywords", [])}
    selected = []
    for artifact in raw_artifacts:
        artifact_domains = set(artifact.get("domains", []))
        artifact_keywords = {keyword.lower() for keyword in artifact.get("keywords", [])}
        if domains and artifact_domains.intersection(domains):
            selected.append(artifact)
            continue
        if keywords and artifact_keywords.intersection(keywords):
            selected.append(artifact)
    return selected


def _preview_signals(raw_events: list[dict], baseline_events: list[dict], filters: dict) -> dict:
    reduced = reduce_observability(raw_events, filters, baseline_events=baseline_events)
    metric_summary = summarize_metrics(reduced["metrics"])
    log_summary = summarize_logs(reduced["logs"])
    user_summary = summarize_user_behavior(reduced["user_events"])
    severity = calculate_incident_severity(metric_summary, log_summary, user_summary)
    return {
        **reduced,
        "incident_score": severity["incident_score"],
        "incident_severity": severity["incident_severity"],
        "severity_hint": severity["severity_hint"],
    }


def _assemble_bundle(metadata: dict, raw_root: Path, filters: dict) -> dict:
    raw_events = _load_jsonl(raw_root / "logs" / "application_logs.jsonl")
    raw_artifacts = _load_json(raw_root / "artifacts" / "catalog.json")

    baseline_events = _slice_raw_events(
        raw_events,
        start=filters.get("baseline_start"),
        end=filters.get("baseline_end"),
    )
    current_events = _slice_raw_events(
        raw_events,
        start=filters.get("start"),
        end=filters.get("end"),
    )
    preview = _preview_signals(current_events, baseline_events, filters)

    return {
        "metadata": metadata,
        "filters": deepcopy(filters),
        "baseline_events": baseline_events,
        "raw_events": current_events,
        "traces": preview["traces"],
        "artifacts": _slice_artifacts(raw_artifacts, filters),
        "logs": preview["logs"],
        "metrics": preview["metrics"],
        "request_path_summary": preview["request_path_summary"],
        "severity_summary": preview["severity_summary"],
        "user_events": preview["user_events"],
        "reduction_summary": preview["reduction_summary"],
        "incident_score": preview["incident_score"],
        "incident_severity": preview["incident_severity"],
        "severity_hint": preview["severity_hint"],
    }


def list_scenarios(data_root: Path) -> list[dict]:
    incidents_root = data_root / "incidents"
    scenarios = []
    for path in sorted(incidents_root.glob("*.json")):
        manifest = _load_json(path)
        scenarios.append(
            {
                "key": path.stem,
                "label": manifest["metadata"]["title"],
                "metadata": manifest["metadata"],
            }
        )
    return scenarios


def load_scenario_bundle(data_root: Path, scenario_key: str) -> dict:
    manifest = _load_json(data_root / "incidents" / f"{scenario_key}.json")
    raw_root = data_root / "raw"
    bundle = _assemble_bundle(manifest["metadata"], raw_root, manifest["filters"])
    timeline_specs = manifest.get("timeline", [])
    if timeline_specs:
        bundle["timeline"] = []
        for stage in timeline_specs:
            stage_filters = _merge_slice_filters(manifest["filters"], stage.get("slice"))
            stage_bundle = _assemble_bundle(manifest["metadata"], raw_root, stage_filters)
            bundle["timeline"].append(
                {
                    "elapsed_sec": stage["elapsed_sec"],
                    "label": stage["label"],
                    "severity_hint": stage_bundle["severity_hint"],
                    "incident_severity": stage_bundle["incident_severity"],
                    "summary": stage["summary"],
                    "operator_note": stage.get("operator_note"),
                    "raw_event_count": len(stage_bundle["raw_events"]),
                    "log_count": len(stage_bundle["logs"]),
                    "trace_count": len(stage_bundle["traces"]),
                    "filters": deepcopy(stage_filters),
                    "baseline_events": deepcopy(stage_bundle["baseline_events"]),
                    "raw_events": deepcopy(stage_bundle["raw_events"]),
                    "traces": deepcopy(stage_bundle["traces"]),
                    "logs": deepcopy(stage_bundle["logs"]),
                    "metrics": deepcopy(stage_bundle["metrics"]),
                    "request_path_summary": deepcopy(stage_bundle["request_path_summary"]),
                    "severity_summary": deepcopy(stage_bundle["severity_summary"]),
                    "user_events": deepcopy(stage_bundle["user_events"]),
                }
            )
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
    replay_bundle["filters"] = deepcopy(stage["filters"])
    replay_bundle["baseline_events"] = deepcopy(stage["baseline_events"])
    replay_bundle["raw_events"] = deepcopy(stage["raw_events"])
    replay_bundle["traces"] = deepcopy(stage["traces"])
    replay_bundle["logs"] = deepcopy(stage["logs"])
    replay_bundle["metrics"] = deepcopy(stage["metrics"])
    replay_bundle["request_path_summary"] = deepcopy(stage["request_path_summary"])
    replay_bundle["severity_summary"] = deepcopy(stage["severity_summary"])
    replay_bundle["user_events"] = deepcopy(stage["user_events"])
    replay_bundle["incident_severity"] = stage["incident_severity"]
    replay_bundle["severity_hint"] = stage["severity_hint"]
    replay_bundle["replay_stage"] = stage
    return replay_bundle
