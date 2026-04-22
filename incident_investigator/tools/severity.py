from __future__ import annotations


def calculate_incident_score(
    metric_summary: dict,
    log_summary: dict,
    user_summary: dict,
) -> int:
    score = 0

    latency_ratio = metric_summary.get("latency_ratio", 0.0)
    max_error_rate_pct = metric_summary.get("max_error_rate_pct", 0.0)
    affected_services = len(metric_summary.get("degraded_services", []))
    error_count = log_summary.get("error_count", 0)
    dropoff_rate_delta = user_summary.get("dropoff_rate_delta", 0.0)

    if latency_ratio >= 4.0:
        score += 35
    elif latency_ratio >= 2.5:
        score += 25
    elif latency_ratio >= 1.8:
        score += 15
    elif latency_ratio >= 1.3:
        score += 8

    if max_error_rate_pct >= 10.0:
        score += 35
    elif max_error_rate_pct >= 5.0:
        score += 25
    elif max_error_rate_pct >= 2.0:
        score += 15
    elif max_error_rate_pct >= 1.0:
        score += 8

    if error_count >= 5:
        score += 5
    elif error_count >= 3:
        score += 3

    if dropoff_rate_delta >= 0.2:
        score += 25
    elif dropoff_rate_delta >= 0.1:
        score += 18
    elif dropoff_rate_delta >= 0.05:
        score += 10

    if affected_services >= 3:
        score += 10
    elif affected_services >= 2:
        score += 5

    return score


def incident_severity_from_score(score: int) -> str:
    if score >= 75:
        return "SEV-1"
    if score >= 50:
        return "SEV-2"
    if score >= 30:
        return "SEV-3"
    return "Watch"


def severity_hint_from_score(score: int) -> str:
    if score >= 75:
        return "SEV-1"
    if score >= 55:
        return "High"
    if score >= 35:
        return "Elevated"
    if score >= 15:
        return "Watch"
    return "Normal"


def calculate_incident_severity(
    metric_summary: dict,
    log_summary: dict,
    user_summary: dict,
) -> dict:
    score = calculate_incident_score(metric_summary, log_summary, user_summary)
    severity = incident_severity_from_score(score)
    return {
        "incident_score": score,
        "incident_severity": severity,
        "severity_hint": severity_hint_from_score(score),
        "summary": (
            f"Calculated severity {severity} from latency ratio {metric_summary.get('latency_ratio', 0.0)}, "
            f"error rate {metric_summary.get('max_error_rate_pct', 0.0)}%, and user drop-off delta "
            f"{round(user_summary.get('dropoff_rate_delta', 0.0) * 100, 1)}%."
        ),
    }
