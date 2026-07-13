"""Inject deterministic OpenShell-like events for Pipecat integration evals."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--delay", type=float, default=2.0)
    args = parser.parse_args()

    time.sleep(args.delay)
    args.path.parent.mkdir(parents=True, exist_ok=True)
    events = [
        {
            "kind": "tool.started",
            "message": "OpenShell observed the agent starting a repository inspection.",
            "tool": "repository-inspector",
        },
        {
            "kind": "policy.denied",
            "message": "OpenShell blocked access to example.invalid.",
            "host": "example.invalid",
        },
        {
            "kind": "tool.finished",
            "message": "OpenShell observed the repository inspection finish.",
            "tool": "repository-inspector",
        },
    ]
    with args.path.open("a", encoding="utf-8") as stream:
        for event in events:
            stream.write(json.dumps(event) + "\n")


if __name__ == "__main__":
    main()
