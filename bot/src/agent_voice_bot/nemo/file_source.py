"""Portable JSONL bridge for OpenShell event collectors and local development."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any


class JsonlEventSource:
    def __init__(self, path: str | Path, poll_interval: float = 0.1):
        self.path = Path(path)
        self.poll_interval = poll_interval
        self._closed = False

    async def events(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        position = 0
        while not self._closed:
            if self.path.exists():
                with self.path.open(encoding="utf-8") as stream:
                    stream.seek(position)
                    for line in stream:
                        try:
                            payload = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if payload.get("run_id") in {None, run_id}:
                            yield payload
                    position = stream.tell()
            await asyncio.sleep(self.poll_interval)

    async def close(self) -> None:
        self._closed = True
