"""NemoHermes deployment checks for agent-voice-bot."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from typing import Any

import httpx


DEFAULT_SANDBOX = "nh"
DEFAULT_BASE_URL = "http://127.0.0.1:8642/v1"
DEFAULT_MODEL = "hermes-agent"


def cli_main() -> None:
    parser = argparse.ArgumentParser(
        description="Check that a local NemoHermes sandbox is ready for agent-voice-bot."
    )
    parser.add_argument(
        "--sandbox",
        default=os.getenv("NEMOHERMES_SANDBOX", DEFAULT_SANDBOX),
        help=f"NemoHermes sandbox name. Defaults to {DEFAULT_SANDBOX!r}.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("AGENT_LOOP_NEMOHERMES_BASE_URL", DEFAULT_BASE_URL),
        help=f"NemoHermes OpenAI-compatible base URL. Defaults to {DEFAULT_BASE_URL!r}.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("AGENT_LOOP_NEMOHERMES_MODEL", DEFAULT_MODEL),
        help=f"Model id to check in /v1/models. Defaults to {DEFAULT_MODEL!r}.",
    )
    parser.add_argument(
        "--completion",
        action="store_true",
        help="Also run a small /v1/chat/completions smoke test.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("NEMOHERMES_CHECK_TIMEOUT_SECS", "15")),
        help="HTTP and CLI timeout in seconds.",
    )
    args = parser.parse_args()

    try:
        asyncio.run(_check(args))
    except Exception as exc:
        print(f"nemohermes check failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


async def _check(args: argparse.Namespace) -> None:
    _check_sandbox(args.sandbox, args.timeout)

    api_root = _api_root(args.base_url)
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        health = await _get_json(client, f"{api_root}/health")
        if health.get("status") != "ok":
            raise RuntimeError(f"Unexpected health response: {health!r}")
        print(f"health ok: {api_root}/health")

        models = await _get_json(client, f"{args.base_url.rstrip('/')}/models")
        model_ids = {
            str(item.get("id"))
            for item in models.get("data", [])
            if isinstance(item, dict) and item.get("id")
        }
        if args.model not in model_ids:
            raise RuntimeError(
                f"Model {args.model!r} not found in NemoHermes models: {sorted(model_ids)}"
            )
        print(f"model ok: {args.model}")

        if args.completion:
            payload = {
                "model": args.model,
                "stream": False,
                "messages": [
                    {
                        "role": "user",
                        "content": "Reply with exactly: NEMOHERMES_OK",
                    }
                ],
            }
            response = await client.post(
                f"{args.base_url.rstrip('/')}/chat/completions",
                headers={"Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            completion = response.json()
            text = _completion_text(completion)
            if not text:
                raise RuntimeError(f"Completion response had no message content: {completion!r}")
            print(f"completion ok: {text[:120]}")

    print("NemoHermes is ready for agent-voice-bot.")
    print("Use: AGENT_LOOP_MODE=nemohermes uv run agent-voice-bot -t eval --port 7860")


def _check_sandbox(sandbox: str, timeout: float) -> None:
    result = subprocess.run(
        ["nemohermes", sandbox, "status"],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        output = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"`nemohermes {sandbox} status` failed: {output}")
    print(f"sandbox ok: {sandbox}")


async def _get_json(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    response = await client.get(url)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object from {url}, got {payload!r}")
    return payload


def _api_root(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return base[:-3]
    return base


def _completion_text(payload: dict[str, Any]) -> str:
    try:
        text = payload["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, TypeError):
        return ""
    if isinstance(text, list):
        return json.dumps(text, ensure_ascii=False)
    return str(text).strip()
