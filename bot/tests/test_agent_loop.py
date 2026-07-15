import asyncio
import json

import pytest
import websockets

from agent_voice_bot.agent_loop import (
    AgentLoopClient,
    AgentLoopFollowupResult,
    AgentLoopRequest,
    AgentLoopRunHandle,
)
from agent_voice_bot.agent_worker import AgentWorker
from agent_voice_bot.config import PLAIN_SPOKEN_OUTPUT_INSTRUCTION, AgentLoopConfig


@pytest.mark.asyncio
async def test_mock_agent_loop_returns_normalized_result():
    client = AgentLoopClient(
        AgentLoopConfig(mode="mock", mock_delay_secs=0, mock_result="ZEBRA-4417")
    )

    result = await client.run(
        AgentLoopRequest(
            user_request="Compare Hermes and OpenClaw",
            reason="requires agent research",
        )
    )

    assert result.status == "completed"
    assert "Compare Hermes and OpenClaw" in result.summary
    # The marker is what the return-path eval asserts comes back to the user.
    assert "ZEBRA-4417" in result.summary


@pytest.mark.asyncio
async def test_rest_agent_loop_requires_url():
    client = AgentLoopClient(AgentLoopConfig(mode="rest", rest_url=None))

    with pytest.raises(ValueError, match="AGENT_LOOP_REST_URL"):
        await client.run(AgentLoopRequest(user_request="x", reason="y"))


@pytest.mark.asyncio
async def test_unknown_agent_loop_mode_fails_fast():
    client = AgentLoopClient(AgentLoopConfig(mode="bogus"))

    with pytest.raises(ValueError, match="Unsupported AGENT_LOOP_MODE"):
        await client.run(AgentLoopRequest(user_request="x", reason="y"))


@pytest.mark.asyncio
async def test_hermes_runs_backend_starts_and_reads_sse(monkeypatch):
    posts = []
    streams = []

    class FakeStreamResponse:
        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            lines = [
                'data: {"event":"message.delta","delta":"half"}',
                "",
                'data: {"event":"message.delta","delta":" done"}',
                "",
                'data: {"event":"run.completed","output":"final answer"}',
                "",
            ]
            for line in lines:
                yield line

    class FakeStreamContext:
        async def __aenter__(self):
            return FakeStreamResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            posts.append({"url": url, "headers": headers, "json": json})
            return _JsonResponse({"run_id": "run_123", "status": "started"})

        def stream(self, method, url, headers=None):
            streams.append({"method": method, "url": url, "headers": headers})
            return FakeStreamContext()

    monkeypatch.setattr("agent_voice_bot.agent_loop.httpx.AsyncClient", FakeAsyncClient)

    client = AgentLoopClient(
        AgentLoopConfig(
            mode="hermes",
            hermes_base_url="http://127.0.0.1:8765",
            hermes_api_key="secret",
            hermes_session_key="voice-session",
        )
    )

    result = await client.run(AgentLoopRequest(user_request="research this", reason="voice"))

    assert result.summary == "final answer"
    assert posts == [
        {
            "url": "http://127.0.0.1:8765/v1/runs",
            "headers": {
                "Content-Type": "application/json",
                "Authorization": "Bearer secret",
                "X-Hermes-Session-Key": "voice-session",
            },
            "json": {
                "model": "hermes-agent",
                "input": "research this",
                "instructions": f"voice {PLAIN_SPOKEN_OUTPUT_INSTRUCTION}",
            },
        }
    ]
    assert streams[0]["url"] == "http://127.0.0.1:8765/v1/runs/run_123/events"


@pytest.mark.asyncio
async def test_nemohermes_uses_openai_compatible_api_defaults(monkeypatch):
    posts = []
    logs = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            posts.append({"url": url, "headers": headers, "json": json})
            return _JsonResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "NemoHermes completed the task.",
                            }
                        }
                    ]
                },
                headers={"X-Hermes-Session-Id": "api-session-123"},
            )

    monkeypatch.setattr("agent_voice_bot.agent_loop.httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        "agent_voice_bot.agent_loop.logger",
        _Logger(info=lambda *args: logs.append(args)),
    )

    client = AgentLoopClient(AgentLoopConfig(mode="nemohermes"))

    result = await client.run(AgentLoopRequest(user_request="research this", reason="voice"))

    assert result.summary == "NemoHermes completed the task."
    assert posts[0]["url"] == "http://127.0.0.1:8642/v1/chat/completions"
    assert posts[0]["headers"] == {"Content-Type": "application/json"}
    assert posts[0]["json"]["model"] == "hermes-agent"
    assert posts[0]["json"]["stream"] is False
    assert "reasoning_effort" not in posts[0]["json"]
    user_message = posts[0]["json"]["messages"][1]
    assert json.loads(user_message["content"])["user_request"] == "research this"
    assert (
        json.loads(user_message["content"])["reason"]
        == f"voice {PLAIN_SPOKEN_OUTPUT_INSTRUCTION}"
    )
    assert PLAIN_SPOKEN_OUTPUT_INSTRUCTION in posts[0]["json"]["messages"][0]["content"]
    assert logs == [
        (
            "{} session id: {}. Tail with: nemohermes nh exec -- hermes logs --session {} -f",
            "NemoHermes",
            "api-session-123",
            "api-session-123",
        )
    ]


@pytest.mark.asyncio
async def test_deepagents_runs_headless_task_in_dedicated_sandbox(monkeypatch):
    seen = []

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"Deep Agents completed the task.\n", b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        seen.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    client = AgentLoopClient(
        AgentLoopConfig(
            mode="deepagents",
            timeout_secs=90,
            deepagents_command="nemoclaw",
            deepagents_sandbox="voice-deepagents",
        )
    )

    result = await client.run(
        AgentLoopRequest(
            user_request="Research the repository",
            reason="voice",
            conversation_summary="The user prefers concise answers.",
        )
    )

    assert result.summary == "Deep Agents completed the task."
    args, kwargs = seen[0]
    assert args[:9] == (
        "nemoclaw", "voice-deepagents", "exec", "--no-tty", "--timeout", "90",
        "--", "dcode", "-n",
    )
    assert "Research the repository" in args[9]
    assert PLAIN_SPOKEN_OUTPUT_INSTRUCTION in args[9]
    assert "The user prefers concise answers." in args[9]
    assert kwargs["stdout"] is asyncio.subprocess.PIPE
    assert kwargs["stderr"] is asyncio.subprocess.PIPE


@pytest.mark.asyncio
async def test_deepagents_reports_headless_command_failure(monkeypatch):
    class FakeProcess:
        returncode = 2

        async def communicate(self):
            return b"", b"sandbox is not ready"

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    client = AgentLoopClient(AgentLoopConfig(mode="deepagents"))

    with pytest.raises(RuntimeError, match="sandbox is not ready"):
        await client.run(AgentLoopRequest(user_request="x", reason="voice"))


@pytest.mark.asyncio
async def test_deepagents_cancellation_terminates_headless_process(monkeypatch):
    started = asyncio.Event()

    class FakeProcess:
        returncode = None
        terminated = False

        async def communicate(self):
            started.set()
            await asyncio.Future()

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        async def wait(self):
            return self.returncode

    process = FakeProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    client = AgentLoopClient(AgentLoopConfig(mode="deepagents"))
    handle = await client.start(AgentLoopRequest(user_request="x", reason="voice"))
    await started.wait()

    await client.stop(handle, "user cancelled")

    assert process.terminated is True


@pytest.mark.asyncio
async def test_openclaw_gateway_backend_sends_steers_and_stops():
    seen_methods = []
    connect_params = {}
    chat_send_seen = asyncio.Event()
    steer_seen = asyncio.Event()
    abort_seen = asyncio.Event()

    async def handler(websocket):
        await websocket.send(
            json.dumps(
                {
                    "type": "event",
                    "event": "connect.challenge",
                    "payload": {"nonce": "n"},
                }
            )
        )
        async for raw in websocket:
            frame = json.loads(raw)
            seen_methods.append(frame["method"])
            if frame["method"] == "connect":
                connect_params.update(frame["params"])
                await websocket.send(
                    json.dumps(
                        {
                            "type": "res",
                            "id": frame["id"],
                            "ok": True,
                            "payload": {
                                "type": "hello-ok",
                                "protocol": 3,
                                "server": {"version": "test", "connId": "conn"},
                                "features": {"methods": [], "events": []},
                                "snapshot": {},
                                "policy": {
                                    "maxPayload": 1000000,
                                    "maxBufferedBytes": 1000000,
                                    "tickIntervalMs": 30000,
                                },
                            },
                        }
                    )
                )
            elif frame["method"] == "chat.send":
                chat_send_seen.set()
                await websocket.send(
                    json.dumps(
                        {
                            "type": "res",
                            "id": frame["id"],
                            "ok": True,
                            "payload": {"runId": frame["params"]["idempotencyKey"], "status": "started"},
                        }
                    )
                )
            elif frame["method"] == "sessions.steer":
                steer_seen.set()
                await websocket.send(
                    json.dumps(
                        {
                            "type": "res",
                            "id": frame["id"],
                            "ok": True,
                            "payload": {"runId": frame["params"]["idempotencyKey"], "messageSeq": 2},
                        }
                    )
                )
            elif frame["method"] == "chat.abort":
                abort_seen.set()
                await websocket.send(
                    json.dumps(
                        {
                            "type": "res",
                            "id": frame["id"],
                            "ok": True,
                            "payload": {"ok": True, "aborted": True},
                        }
                    )
                )

    server = await websockets.serve(handler, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        client = AgentLoopClient(
            AgentLoopConfig(
                mode="openclaw",
                openclaw_gateway_url=f"ws://127.0.0.1:{port}",
                openclaw_session_key="agent:main:voice:test",
            )
        )

        handle = await client.start(AgentLoopRequest(user_request="do it", reason="voice"))
        await asyncio.wait_for(chat_send_seen.wait(), timeout=1)

        followup = await client.send_followup(handle, "add this detail")
        await asyncio.wait_for(steer_seen.wait(), timeout=1)

        await client.stop(handle, "cancelled")
        await asyncio.wait_for(abort_seen.wait(), timeout=1)

        assert followup.applied is True
        assert "connect" in seen_methods
        assert connect_params["minProtocol"] == 4
        assert connect_params["maxProtocol"] == 4
        assert "chat.send" in seen_methods
        assert "sessions.steer" in seen_methods
        assert "chat.abort" in seen_methods
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_agent_loop_worker_forwards_busy_followup_to_backend():
    class FakeClient:
        def __init__(self):
            self.followups = []

        async def send_followup(self, handle, user_input):
            self.followups.append((handle, user_input))
            return AgentLoopFollowupResult(applied=True, status="steered")

    fake_client = FakeClient()
    worker = AgentWorker(fake_client)
    handle = AgentLoopRunHandle(run_id="remote-run", backend="openclaw")
    worker._active_job_id = "job-active"
    worker._active_run_handle = handle

    responses = []

    async def capture_response(job_id, response=None, *, status=None, urgent=False):
        responses.append(
            {
                "job_id": job_id,
                "response": response,
                "status": status,
                "urgent": urgent,
            }
        )

    worker.send_job_response = capture_response

    await worker.run_agent_loop(
        _Message(job_id="job-followup", payload={"input": "tighten the scope"})
    )

    assert fake_client.followups == [(handle, "tighten the scope")]
    assert responses == [
        {
            "job_id": "job-followup",
            "response": {
                "kind": "steering",
                "active_job_id": "job-active",
                "applied": True,
                "status": "steered",
                "raw": None,
            },
            "status": None,
            "urgent": True,
        }
    ]


class _JsonResponse:
    def __init__(self, payload, *, headers=None):
        self._payload = payload
        self.headers = {"content-type": "application/json"}
        if headers:
            self.headers.update(headers)
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _Message:
    def __init__(self, job_id, payload):
        self.job_id = job_id
        self.payload = payload


class _Logger:
    def __init__(self, *, info):
        self.info = info
