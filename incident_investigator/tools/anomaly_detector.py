from __future__ import annotations


def detect_anomalies(metric_summary: dict, log_summary: dict, user_summary: dict) -> list[dict]:
    anomalies = []

    if metric_summary["max_latency_ms"] > metric_summary["baseline_latency_ms"] * 2:
        anomalies.append(
            {
                "type": "latency_spike",
                "service": metric_summary["highest_latency_service"],
                "severity": "High",
                "description": metric_summary["latency_summary"],
            }
        )

    if log_summary["error_count"] > log_summary["warning_count"]:
        anomalies.append(
            {
                "type": "error_spike",
                "service": log_summary["top_error_component"],
                "severity": "High",
                "description": log_summary["error_summary"],
            }
        )

    if user_summary["dropoff_rate_delta"] >= 0.15:
        anomalies.append(
            {
                "type": "user_dropoff",
                "service": user_summary["most_impacted_flow"],
                "severity": "Medium",
                "description": user_summary["dropoff_summary"],
            }
        )

    return anomalies

