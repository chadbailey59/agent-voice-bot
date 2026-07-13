"""Verify the control-plane side of a Nemo Pipecat eval run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()

    events = [json.loads(line) for line in args.path.read_text().splitlines() if line]
    kinds = {event["kind"] for event in events}
    required = {"run_started", "tool_started", "policy_denied", "tool_finished", "completed"}
    missing = required - kinds
    if missing:
        raise SystemExit(f"Missing Nemo telemetry events: {sorted(missing)}")
    if not any(event.get("source") == "openshell" for event in events):
        raise SystemExit("No OpenShell-sourced events were recorded")
    print(f"Nemo telemetry verified: {len(events)} events; kinds={sorted(kinds)}")


if __name__ == "__main__":
    main()
