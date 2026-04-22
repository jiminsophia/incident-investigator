from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from math import ceil


REQUEST_EVENT_TYPES = {"service_request", "dependency_call"}
JOURNEY_EVENT_TYPES = {"journey", "user_journey"}


def _entry_point(event: dict) -> str | None:
    return event.get("entry_point") or event.get("entrypoint")


def _journey_name(event: dict) -> str | None:
    return event.get("journey") or event.get("flow")


def _retry_count(event: dict) -> int:
    return int(event.get("retry", event.get("retry_count", 0)) or 0)


def parse_timestamp(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)


def format_timestamp(timestamp: datetime) -> str:
    return timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def percentile(values: list[int | float], pct: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, ceil((pct / 100) * len(ordered)) - 1)
    return int(round(ordered[index]))


def is_request_event(event: dict) -> bool:
    return event.get("event_type") in REQUEST_EVENT_TYPES


def is_journey_event(event: dict) -> bool:
    return event.get("event_type") in JOURNEY_EVENT_TYPES


def is_error_event(event: dict) -> bool:
    status_code = event.get("status_code")
    return bool(
        event.get("timeout")
        or event.get("exception")
        or event.get("outcome") == "error"
        or (status_code is not None and status_code >= 500)
    )


def _build_baseline_latency_map(baseline_events: list[dict]) -> dict[str, int]:
    baseline_latencies: dict[str, list[int]] = defaultdict(list)
    for event in baseline_events:
        if not is_request_event(event):
            continue
        latency_ms = event.get("latency_ms")
        if latency_ms is None:
            continue
        baseline_latencies[event["service"]].append(latency_ms)
    return {
        service: percentile(latencies, 95)
        for service, latencies in baseline_latencies.items()
    }


def is_warn_event(event: dict, baseline_latency_map: dict[str, int]) -> bool:
    if is_error_event(event):
        return False

    status_code = event.get("status_code") or 0
    latency_ms = event.get("latency_ms") or 0
    baseline_p95_ms = baseline_latency_map.get(event.get("service", ""), 0)

    if _retry_count(event) > 0:
        return True
    if 400 <= status_code < 500:
        return True
    if baseline_p95_ms and latency_ms > baseline_p95_ms * 1.5:
        return True
    if event.get("outcome") in {"degraded", "abandoned", "dropped"}:
        return True
    return False


def _service_severity_score(latency_ratio: float, error_rate_pct: float, request_count: int) -> int:
    score = 0
    if latency_ratio >= 4.0:
        score += 50
    elif latency_ratio >= 2.5:
        score += 35
    elif latency_ratio >= 1.8:
        score += 20
    elif latency_ratio >= 1.3:
        score += 8

    if error_rate_pct >= 20.0:
        score += 45
    elif error_rate_pct >= 10.0:
        score += 35
    elif error_rate_pct >= 5.0:
        score += 25
    elif error_rate_pct >= 2.0:
        score += 14
    elif error_rate_pct >= 1.0:
        score += 6

    if request_count >= 4:
        score += 5
    return score


def _severity_label_from_score(score: int) -> str:
    if score >= 85:
        return "Critical"
    if score >= 60:
        return "High"
    if score >= 30:
        return "Medium"
    return "Low"


def derive_service_metrics(current_events: list[dict], baseline_events: list[dict]) -> list[dict]:
    current_by_service: dict[str, list[dict]] = defaultdict(list)
    baseline_by_service: dict[str, list[dict]] = defaultdict(list)

    for event in current_events:
        if is_request_event(event):
            current_by_service[event["service"]].append(event)

    for event in baseline_events:
        if is_request_event(event):
            baseline_by_service[event["service"]].append(event)

    services = []
    seen_services = set()
    for event in current_events + baseline_events:
        service = event.get("service")
        if service and service not in seen_services:
            seen_services.add(service)
            services.append(service)

    metrics = []
    for service in services:
        current_samples = current_by_service.get(service, [])
        baseline_samples = baseline_by_service.get(service, [])
        if not current_samples and not baseline_samples:
            continue

        current_latencies = [event["latency_ms"] for event in current_samples if event.get("latency_ms") is not None]
        baseline_latencies = [event["latency_ms"] for event in baseline_samples if event.get("latency_ms") is not None]
        current_p95_ms = percentile(current_latencies, 95)
        baseline_p95_ms = percentile(baseline_latencies, 95) or percentile(current_latencies, 50)
        current_errors = sum(1 for event in current_samples if is_error_event(event))
        baseline_errors = sum(1 for event in baseline_samples if is_error_event(event))
        current_error_rate_pct = round((current_errors / len(current_samples)) * 100, 1) if current_samples else 0.0
        baseline_error_rate_pct = round((baseline_errors / len(baseline_samples)) * 100, 1) if baseline_samples else 0.0
        latency_ratio = round((current_p95_ms / baseline_p95_ms), 2) if baseline_p95_ms else 0.0
        severity_score = _service_severity_score(latency_ratio, current_error_rate_pct, len(current_samples))
        metrics.append(
            {
                "service": service,
                "request_count": len(current_samples),
                "baseline_request_count": len(baseline_samples),
                "baseline_p95_ms": baseline_p95_ms,
                "current_p95_ms": current_p95_ms,
                "latency_ratio": latency_ratio,
                "error_rate_pct": current_error_rate_pct,
                "baseline_error_rate_pct": baseline_error_rate_pct,
                "impacted_entry_points": sorted(
                    {_entry_point(event) for event in current_samples if _entry_point(event)}
                ),
                "severity_score": severity_score,
                "severity": _severity_label_from_score(severity_score),
            }
        )

    return sorted(metrics, key=lambda item: (-item["severity_score"], -item["current_p95_ms"], item["service"]))


def _build_request_message(event: dict) -> str:
    operation = event.get("operation") or event.get("event_type", "event")
    message = (
        f"{operation} outcome={event.get('outcome', 'unknown')}"
        f" status={event.get('status_code', 'n/a')}"
    )
    if event.get("downstream"):
        message += f" downstream={event['downstream']}"
    if event.get("latency_ms") is not None:
        message += f" latency={event['latency_ms']}ms"
    if _retry_count(event):
        message += f" retry={_retry_count(event)}"
    if event.get("timeout"):
        message += " timeout=true"
    if event.get("exception"):
        message += f" exception={event['exception']}"
    return message


def derive_log_records(current_events: list[dict], baseline_events: list[dict]) -> list[dict]:
    baseline_latency_map = _build_baseline_latency_map(baseline_events)
    records = []

    for event in sorted(current_events, key=lambda item: item["timestamp"]):
        if is_request_event(event):
            if is_error_event(event):
                level = "ERROR"
            elif is_warn_event(event, baseline_latency_map):
                level = "WARN"
            else:
                level = "INFO"
            component = event["service"]
            message = _build_request_message(event)
        elif is_journey_event(event):
            outcome = event.get("outcome", "unknown")
            level = "WARN" if outcome in {"abandoned", "dropped"} else "INFO"
            component = _entry_point(event) or "frontend-web"
            message = (
                f"journey={_journey_name(event) or 'unknown'} "
                f"step={event.get('journey_step') or event.get('last_completed_step') or 'unknown'}"
                f" outcome={outcome}"
            )
        else:
            continue

        records.append(
            {
                "timestamp": event["timestamp"],
                "level": level,
                "component": component,
                "message": message,
                "request_id": event.get("request_id"),
                "trace_id": event.get("trace_id"),
                "session_id": event.get("session_id"),
                "entry_point": _entry_point(event),
                "latency_ms": event.get("latency_ms"),
                "status_code": event.get("status_code"),
                "timeout": event.get("timeout", False),
            }
        )

    return records


def _conversion_summary(events: list[dict]) -> dict[str, dict]:
    by_flow: dict[str, dict[str, set[str] | Counter]] = defaultdict(
        lambda: {
            "started": set(),
            "completed": set(),
            "abandoned": set(),
            "exit_steps": Counter(),
        }
    )

    for event in events:
        if not is_journey_event(event):
            continue
        flow = _journey_name(event)
        session_id = event.get("session_id")
        if not flow or not session_id:
            continue

        flow_state = by_flow[flow]
        outcome = event.get("outcome")
        journey_step = event.get("journey_step") or event.get("last_completed_step") or "unknown"
        if outcome in {"started", "begin"}:
            flow_state["started"].add(session_id)
        elif outcome in {"completed", "success"}:
            flow_state["started"].add(session_id)
            flow_state["completed"].add(session_id)
        elif outcome in {"abandoned", "dropped"}:
            flow_state["started"].add(session_id)
            flow_state["abandoned"].add(session_id)
            flow_state["exit_steps"][journey_step] += 1
        else:
            flow_state["started"].add(session_id)

    return by_flow


def derive_user_journeys(current_events: list[dict], baseline_events: list[dict]) -> list[dict]:
    baseline_summary = _conversion_summary(baseline_events)
    current_summary = _conversion_summary(current_events)
    flows = []
    seen = set()

    for event in current_events + baseline_events:
        flow = _journey_name(event)
        if flow and flow not in seen:
            flows.append(flow)
            seen.add(flow)

    journey_metrics = []
    for flow in flows:
        baseline = baseline_summary.get(flow, {"started": set(), "completed": set(), "abandoned": set(), "exit_steps": Counter()})
        current = current_summary.get(flow, {"started": set(), "completed": set(), "abandoned": set(), "exit_steps": Counter()})

        baseline_started = len(baseline["started"])
        current_started = len(current["started"])
        baseline_conversion = round(len(baseline["completed"]) / baseline_started, 2) if baseline_started else 0.0
        current_conversion = round(len(current["completed"]) / current_started, 2) if current_started else 0.0
        dropoff_delta = round(max(0.0, baseline_conversion - current_conversion), 2)
        abandonment_rate = round(len(current["abandoned"]) / current_started, 2) if current_started else 0.0
        top_exit_step = current["exit_steps"].most_common(1)[0][0] if current["exit_steps"] else "none"

        journey_metrics.append(
            {
                "flow": flow,
                "baseline_conversion_rate": baseline_conversion,
                "current_conversion_rate": current_conversion,
                "dropoff_rate_delta": dropoff_delta,
                "abandonment_rate": abandonment_rate,
                "started_sessions": current_started,
                "top_exit_step": top_exit_step,
            }
        )

    return sorted(journey_metrics, key=lambda item: (-item["dropoff_rate_delta"], item["flow"]))


def summarize_request_paths(current_events: list[dict]) -> dict:
    request_events = [event for event in current_events if is_request_event(event)]
    entry_points = Counter(
        _entry_point(event) for event in request_events if _entry_point(event)
    )
    operations = Counter(
        f"{event['service']}::{event['operation']}"
        for event in request_events
        if event.get("service") and event.get("operation")
    )
    failing_paths = Counter(
        f"{_entry_point(event) or 'unknown'} -> {event.get('service', 'unknown')}"
        for event in request_events
        if is_error_event(event)
    )
    primary_entry_point = entry_points.most_common(1)[0][0] if entry_points else "unknown"
    top_path = failing_paths.most_common(1)[0][0] if failing_paths else "unknown"

    return {
        "primary_entry_point": primary_entry_point,
        "top_entry_points": [entry for entry, _ in entry_points.most_common(3)],
        "impacted_operations": [operation for operation, _ in operations.most_common(4)],
        "failing_path": top_path,
        "path_summary": (
            f"{primary_entry_point} generated most of the degraded traffic; the hottest failing path was {top_path}."
            if request_events
            else "No request path data is available yet."
        ),
    }


def calculate_incident_severity(
    service_metrics: list[dict],
    user_journeys: list[dict],
    log_records: list[dict],
) -> dict:
    highest_latency_ratio = max((item["latency_ratio"] for item in service_metrics), default=0.0)
    highest_error_rate = max((item["error_rate_pct"] for item in service_metrics), default=0.0)
    highest_dropoff = max((item["dropoff_rate_delta"] for item in user_journeys), default=0.0)
    impacted_services = [
        item["service"]
        for item in service_metrics
        if item["latency_ratio"] >= 1.8 or item["error_rate_pct"] >= 2.0
    ]
    error_count = sum(1 for record in log_records if record["level"] == "ERROR")

    score = 0
    if highest_latency_ratio >= 4.0:
        score += 35
    elif highest_latency_ratio >= 2.5:
        score += 25
    elif highest_latency_ratio >= 1.8:
        score += 15

    if highest_error_rate >= 10.0:
        score += 35
    elif highest_error_rate >= 5.0:
        score += 25
    elif highest_error_rate >= 2.0:
        score += 15
    elif highest_error_rate >= 1.0:
        score += 8

    if highest_dropoff >= 0.2:
        score += 25
    elif highest_dropoff >= 0.1:
        score += 18
    elif highest_dropoff >= 0.05:
        score += 10

    if len(impacted_services) >= 3:
        score += 10
    elif len(impacted_services) >= 2:
        score += 5

    if error_count >= 5:
        score += 5
    elif error_count >= 3:
        score += 3

    if score >= 75:
        severity = "SEV-1"
    elif score >= 50:
        severity = "SEV-2"
    elif score >= 30:
        severity = "SEV-3"
    else:
        severity = "Watch"

    return {
        "severity": severity,
        "incident_score": score,
        "highest_latency_ratio": round(highest_latency_ratio, 2),
        "highest_error_rate_pct": highest_error_rate,
        "highest_dropoff_delta": highest_dropoff,
        "affected_services": impacted_services,
        "summary": (
            f"Calculated severity {severity} from latency ratio {round(highest_latency_ratio, 2)}, "
            f"error rate {highest_error_rate}%, and user drop-off delta {round(highest_dropoff * 100, 1)}%."
        ),
    }


def select_focus_window(
    current_events: list[dict],
    baseline_events: list[dict],
    bucket_seconds: int = 90,
) -> dict:
    if not current_events:
        return {
            "label": "not enough events yet",
            "start": None,
            "end": None,
            "events": [],
            "incident_score": 0,
            "severity": "Watch",
        }

    ordered = sorted(current_events, key=lambda item: item["timestamp"])
    window_start = parse_timestamp(ordered[0]["timestamp"])
    window_end = parse_timestamp(ordered[-1]["timestamp"])

    best = None
    bucket_start = window_start
    while bucket_start <= window_end:
        bucket_end = bucket_start + timedelta(seconds=bucket_seconds)
        bucket_events = [
            event
            for event in ordered
            if bucket_start <= parse_timestamp(event["timestamp"]) <= bucket_end
        ]
        if bucket_events:
            metrics = derive_service_metrics(bucket_events, baseline_events)
            journeys = derive_user_journeys(bucket_events, baseline_events)
            logs = derive_log_records(bucket_events, baseline_events)
            severity_summary = calculate_incident_severity(metrics, journeys, logs)
            candidate = {
                "label": (
                    f"{format_timestamp(bucket_start)[11:16]}-{format_timestamp(bucket_end)[11:16]} UTC"
                ),
                "start": format_timestamp(bucket_start),
                "end": format_timestamp(bucket_end),
                "events": bucket_events,
                "incident_score": severity_summary["incident_score"],
                "severity": severity_summary["severity"],
            }
            if best is None or candidate["incident_score"] > best["incident_score"]:
                best = candidate
        bucket_start = bucket_end

    if best is None:
        return {
            "label": "not enough events yet",
            "start": None,
            "end": None,
            "events": [],
            "incident_score": 0,
            "severity": "Watch",
        }
    return best
