from __future__ import annotations

import json
import sys
from pathlib import Path

from incident_investigator.orchestration.coordinator import CoordinatorAgent
from incident_investigator.tools.data_loader import load_scenario_bundle


def main() -> None:
    scenario = sys.argv[1] if len(sys.argv) > 1 else "checkout_latency_incident"
    data_root = Path(__file__).parent / "incident_investigator" / "data"
    bundle = load_scenario_bundle(data_root, scenario)
    report = CoordinatorAgent().run(bundle)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
