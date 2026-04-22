from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path


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


def _select_latest_snapshot(snapshots: list[dict], snapshot_at: str | None) -> dict | None:
    if not snapshots:
        return None
    eligible = [
        snapshot for snapshot in snapshots
        if snapshot_at is None or snapshot["timestamp"] <= snapshot_at
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda item: item["timestamp"])


def _format_window_label(start: str | None, end: str | None) -> str:
    if not start or not end:
        return "unknown"
    return f"{start[11:16]}-{end[11:16]} UTC"


def _slice_logs(raw_logs: list[dict], filters: dict) -> list[dict]:
    components = set(filters.get("components", []))
    return [
        log
        for log in raw_logs
        if _within_window(log["timestamp"], filters.get("start"), filters.get("end"))
        and (not components or log["component"] in components)
    ]


def _slice_traces(raw_traces: list[dict], filters: dict) -> list[dict]:
    services = set(filters.get("services", []))
    sliced = []
    for trace in raw_traces:
        if not _within_window(trace["timestamp"], filters.get("start"), filters.get("end")):
            continue
        if services and not any(span["service"] in services for span in trace["spans"]):
            continue
        sliced.append(
            {
                "trace_id": trace["trace_id"],
                "window": _format_window_label(filters.get("start"), filters.get("end")),
                "duration_ms": trace["duration_ms"],
                "spans": trace["spans"],
            }
        )
    return sliced


def _slice_metrics(raw_metric_snapshots: list[dict], filters: dict) -> list[dict]:
    snapshot = _select_latest_snapshot(raw_metric_snapshots, filters.get("metric_snapshot_at"))
    if snapshot is None:
        return []
    services = set(filters.get("services", []))
    return [
        item
        for item in snapshot["services"]
        if not services or item["service"] in services
    ]


def _slice_user_events(raw_user_snapshots: list[dict], filters: dict) -> list[dict]:
    snapshot = _select_latest_snapshot(raw_user_snapshots, filters.get("user_snapshot_at"))
    if snapshot is None:
        return []
    flows = set(filters.get("flows", []))
    return [
        item
        for item in snapshot["flows"]
        if not flows or item["flow"] in flows
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


def _assemble_bundle(metadata: dict, raw_root: Path, filters: dict) -> dict:
    raw_logs = _load_jsonl(raw_root / "logs" / "application_logs.jsonl")
    raw_traces = _load_jsonl(raw_root / "traces" / "distributed_traces.jsonl")
    raw_metric_snapshots = _load_json(raw_root / "metrics" / "service_metrics.json")
    raw_user_snapshots = _load_json(raw_root / "user_events" / "conversion_snapshots.json")
    raw_artifacts = _load_json(raw_root / "artifacts" / "catalog.json")

    return {
        "metadata": metadata,
        "logs": _slice_logs(raw_logs, filters),
        "metrics": _slice_metrics(raw_metric_snapshots, filters),
        "traces": _slice_traces(raw_traces, filters),
        "user_events": _slice_user_events(raw_user_snapshots, filters),
        "artifacts": _slice_artifacts(raw_artifacts, filters),
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
                    "severity_hint": stage["severity_hint"],
                    "summary": stage["summary"],
                    "operator_note": stage.get("operator_note"),
                    "log_count": len(stage_bundle["logs"]),
                    "trace_count": len(stage_bundle["traces"]),
                    "metrics": stage_bundle["metrics"],
                    "user_events": stage_bundle["user_events"],
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
    replay_bundle["logs"] = bundle["logs"][: stage["log_count"]]
    replay_bundle["traces"] = bundle["traces"][: stage["trace_count"]]
    replay_bundle["user_events"] = stage["user_events"]
    replay_bundle["metrics"] = stage["metrics"]
    replay_bundle["replay_stage"] = stage
    return replay_bundle
