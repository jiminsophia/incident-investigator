from __future__ import annotations

import unittest
from pathlib import Path

from incident_investigator.tools.data_loader import load_scenario_bundle
from incident_investigator.tools.event_processing import (
    calculate_incident_severity,
    derive_log_records,
    derive_service_metrics,
    derive_user_journeys,
    select_focus_window,
)


DATA_ROOT = Path(__file__).resolve().parents[1] / "incident_investigator" / "data"


class EventProcessingTests(unittest.TestCase):
    def test_checkout_events_reduce_into_latency_and_error_signals(self) -> None:
        bundle = load_scenario_bundle(DATA_ROOT, "checkout_latency_incident")

        metrics = derive_service_metrics(bundle["raw_events"], bundle["baseline_events"])
        logs = derive_log_records(bundle["raw_events"], bundle["baseline_events"])
        user_events = derive_user_journeys(bundle["raw_events"], bundle["baseline_events"])
        severity = calculate_incident_severity(metrics, user_events, logs)

        payment_metric = next(item for item in metrics if item["service"] == "payment-service")
        checkout_flow = next(item for item in user_events if item["flow"] == "checkout_completion")

        self.assertGreaterEqual(payment_metric["error_rate_pct"], 50.0)
        self.assertGreater(payment_metric["latency_ratio"], 3.0)
        self.assertGreaterEqual(checkout_flow["dropoff_rate_delta"], 0.2)
        self.assertEqual(severity["severity"], "SEV-1")
        self.assertTrue(any(log["level"] == "ERROR" for log in logs))

    def test_focus_window_finds_dense_search_regression_slice(self) -> None:
        bundle = load_scenario_bundle(DATA_ROOT, "search_relevance_regression")
        focused = select_focus_window(bundle["raw_events"], bundle["baseline_events"])

        self.assertIsNotNone(focused["start"])
        self.assertGreater(focused["incident_score"], 0)
        self.assertGreaterEqual(len(focused["events"]), 3)
        self.assertIn(focused["severity"], {"SEV-1", "SEV-2", "SEV-3", "Watch"})


if __name__ == "__main__":
    unittest.main()
