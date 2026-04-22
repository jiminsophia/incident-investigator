from __future__ import annotations


def detect_anomalies(
    metric_summary: dict,
    log_summary: dict,
    user_summary: dict,
    severity_summary: dict,
) -> list[dict]:
    anomalies = []

    if metric_summary["latency_ratio"] >= 1.8:
        anomalies.append(
            {
                "type": "latency_spike",
                "service": metric_summary["highest_latency_service"],
                "severity": "High" if metric_summary["latency_ratio"] >= 2.5 else "Medium",
                "description": metric_summary["latency_summary"],
            }
        )

    if metric_summary["max_error_rate_pct"] >= 2.0 or log_summary["error_count"] >= 2:
        anomalies.append(
            {
                "type": "error_spike",
                "service": log_summary["top_error_component"],
                "severity": "High" if metric_summary["max_error_rate_pct"] >= 5.0 else "Medium",
                "description": log_summary["error_summary"],
            }
        )

    if user_summary["dropoff_rate_delta"] >= 0.05:
        anomalies.append(
            {
                "type": "user_dropoff",
                "service": user_summary["most_impacted_flow"],
                "severity": "High" if user_summary["dropoff_rate_delta"] >= 0.15 else "Medium",
                "description": user_summary["dropoff_summary"],
            }
        )

    if severity_summary["severity"] in {"SEV-1", "SEV-2", "SEV-3"}:
        anomalies.append(
            {
                "type": "incident_severity",
                "service": ", ".join(severity_summary["affected_services"][:3]) or "unknown",
                "severity": severity_summary["severity"],
                "description": severity_summary["summary"],
            }
        )

    return anomalies
