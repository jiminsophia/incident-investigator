from __future__ import annotations


def summarize_user_behavior(user_events: list[dict]) -> dict:
    if not user_events:
        return {
            "most_impacted_flow": "unknown",
            "dropoff_rate_delta": 0.0,
            "dropoff_summary": "No user impact is visible yet.",
        }

    most_impacted = max(user_events, key=lambda item: item["dropoff_rate_delta"])
    return {
        "most_impacted_flow": most_impacted["flow"],
        "dropoff_rate_delta": most_impacted["dropoff_rate_delta"],
        "dropoff_summary": (
            f"{most_impacted['flow']} drop-off increased by "
            f"{round(most_impacted['dropoff_rate_delta'] * 100, 1)}% after the incident."
        ),
    }
