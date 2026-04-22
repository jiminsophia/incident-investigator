from __future__ import annotations

import unittest
from pathlib import Path

from incident_investigator.tools.data_loader import list_scenarios, load_scenario_bundle


DATA_ROOT = Path(__file__).resolve().parents[1] / "incident_investigator" / "data"


class DataLoaderTests(unittest.TestCase):
    def test_list_scenarios_reads_incident_manifests(self) -> None:
        scenarios = list_scenarios(DATA_ROOT)
        self.assertEqual(
            [item["key"] for item in scenarios],
            ["checkout_latency_incident", "search_relevance_regression"],
        )

    def test_checkout_bundle_is_assembled_from_raw_data(self) -> None:
        bundle = load_scenario_bundle(DATA_ROOT, "checkout_latency_incident")

        self.assertEqual(bundle["metadata"]["severity"], "SEV-1")
        self.assertGreater(len(bundle["raw_events"]), 10)
        self.assertGreater(len(bundle["logs"]), 6)
        self.assertTrue(any(log["level"] == "INFO" for log in bundle["logs"]))
        self.assertGreaterEqual(len(bundle["traces"]), 4)
        self.assertEqual(bundle["metrics"][0]["service"], "checkout-api")
        self.assertIn(bundle["incident_severity"], {"SEV-1", "SEV-2"})
        self.assertEqual(len(bundle["timeline"]), 5)
        self.assertGreater(bundle["timeline"][0]["log_count"], 0)

    def test_search_bundle_keeps_healthy_and_incident_signals_together(self) -> None:
        bundle = load_scenario_bundle(DATA_ROOT, "search_relevance_regression")

        self.assertEqual(bundle["metadata"]["severity"], "SEV-2")
        self.assertGreater(len(bundle["raw_events"]), 8)
        self.assertTrue(any(log["level"] == "INFO" for log in bundle["logs"]))
        self.assertTrue(any(log["level"] == "ERROR" for log in bundle["logs"]))
        self.assertEqual(
            sorted(metric["service"] for metric in bundle["metrics"]),
            ["frontend-web", "model-gateway", "ranking-service", "search-api"],
        )
        self.assertIn(bundle["incident_severity"], {"SEV-1", "SEV-2", "SEV-3"})


if __name__ == "__main__":
    unittest.main()
