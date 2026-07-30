import asyncio
import json

import pytest
import websockets

from agent_voice_bot.config import AGENT_LOOP_INSTRUCTION, OpenClawConfig
from agent_voice_bot.openclaw import OpenClawRuntime, collect_result

HELLO_OK = {
    "type": "hello-ok",
    "protocol": 4,
    "server": {"version": "test", "connId": "conn"},
    "features": {"methods": [], "events": []},
    "snapshot": {},
    "policy": {
        "maxPayload": 1000000,
        "maxBufferedBytes": 1000000,
        "tickIntervalMs": 30000,
    },
}


class FakeGateway:
    """A stand-in OpenClaw Gateway that records calls and scripts chat events.

    Real websockets rather than a mocked connection: the connect handshake and
    the request/response correlation are the parts most likely to break, and a
    fake object would assert nothing about either.
    """

    def __init__(self, chat_events=()):
        self.methods: list[str] = []
        self.params: dict[str, dict] = {}
        self.chat_events = list(chat_events)
        self._server = None

    async def __aenter__(self):
        self._server = await websockets.serve(self._handler, "127.0.0.1", 0)
        return self

    async def __aexit__(self, *exc_info):
        self._server.close()
        await self._server.wait_closed()

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self._server.sockets[0].getsockname()[1]}"

    def config(self, **overrides) -> OpenClawConfig:
        return OpenClawConfig(
            gateway_url=self.url,
            session_key="agent:main:voice:test",
            timeout_secs=5,
            **overrides,
        )

    async def _handler(self, websocket):
        await websocket.send(
            json.dumps({"type": "event", "event": "connect.challenge", "payload": {"nonce": "n"}})
        )
        async for raw in websocket:
            frame = json.loads(raw)
            method = frame["method"]
            self.methods.append(method)
            self.params[method] = frame.get("params") or {}
            await websocket.send(json.dumps(self._response(frame)))
            if method == "chat.send":
                run_id = frame["params"]["idempotencyKey"]
                for event in self.chat_events:
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "event",
                                "event": "chat",
                                "payload": {"runId": run_id, **event},
                            }
                        )
                    )

    def _response(self, frame):
        method = frame["method"]
        if method == "connect":
            payload = HELLO_OK
        elif method == "chat.send":
            payload = {"runId": frame["params"]["idempotencyKey"], "status": "started"}
        elif method == "sessions.steer":
            payload = {"messageSeq": 2}
        elif method == "chat.abort":
            payload = {"ok": True, "aborted": True}
        else:
            payload = {}
        return {"type": "res", "id": frame["id"], "ok": True, "payload": payload}


@pytest.mark.asyncio
async def test_start_steer_and_stop_reach_the_gateway():
    async with FakeGateway() as gateway:
        runtime = OpenClawRuntime(gateway.config())

        handle = await runtime.start("do it")
        await runtime.send_followup(handle, "add this detail")
        await runtime.stop(handle, "cancelled")

        # stop() dials its own connection, hence the second "connect".
        assert gateway.methods == [
            "connect", "chat.send", "sessions.steer", "connect", "chat.abort",
        ]
        assert gateway.params["connect"]["minProtocol"] == 4
        assert gateway.params["connect"]["maxProtocol"] == 4
        assert gateway.params["chat.send"]["sessionKey"] == "agent:main:voice:test"
        assert gateway.params["sessions.steer"]["message"] == "add this detail"
        assert gateway.params["chat.abort"]["runId"] == handle.run_id


@pytest.mark.asyncio
async def test_stop_requires_gateway_confirmation():
    class UnconfirmedAbortGateway(FakeGateway):
        def _response(self, frame):
            response = super()._response(frame)
            if frame["method"] == "chat.abort":
                response["payload"] = {"ok": True, "aborted": False}
            return response

    async with UnconfirmedAbortGateway() as gateway:
        runtime = OpenClawRuntime(gateway.config())
        handle = await runtime.start("do it")

        with pytest.raises(RuntimeError, match="did not confirm"):
            await runtime.stop(handle, "cancelled")


@pytest.mark.asyncio
async def test_abort_still_reaches_the_gateway_after_the_run_is_cancelled():
    """The path stop_agent_loop actually takes.

    A cancellation lands inside events(), whose `finally` closes the stream
    connection while unwinding. stop() runs afterwards, so it cannot use that
    socket: an earlier version reused it and silently aborted nothing, leaving
    the agent running in the sandbox while the user was told it had stopped.
    """
    async with FakeGateway() as gateway:  # no scripted events: the run stays open
        runtime = OpenClawRuntime(gateway.config())
        handle = await runtime.start("do it")

        consuming = asyncio.create_task(collect_result(runtime.events(handle)))
        await asyncio.sleep(0.05)
        consuming.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consuming

        await runtime.stop(handle, "Cancelled by the voice loop.")

    assert "chat.abort" in gateway.methods
    assert gateway.params["chat.abort"]["runId"] == handle.run_id


@pytest.mark.asyncio
async def test_forwarded_work_carries_the_agent_instruction():
    async with FakeGateway() as gateway:
        runtime = OpenClawRuntime(gateway.config())
        await runtime.start("do it")

    # The agent's reply gets spoken aloud, so the instruction that asks for one
    # short plain-text answer has to actually reach the agent.
    message = gateway.params["chat.send"]["message"]
    assert message.startswith("do it")
    assert AGENT_LOOP_INSTRUCTION in message


@pytest.mark.asyncio
async def test_streamed_deltas_accumulate_into_the_final_result():
    events = [
        {"state": "delta", "message": {"text": "wor"}},
        {"state": "delta", "message": {"text": "king"}},
        {"state": "final", "message": {"text": "ZEBRA-4417"}},
    ]
    async with FakeGateway(events) as gateway:
        runtime = OpenClawRuntime(gateway.config())
        handle = await runtime.start("do it")
        result = await asyncio.wait_for(collect_result(runtime.events(handle)), timeout=5)

    assert result.status == "completed"
    assert result.summary == "ZEBRA-4417"


@pytest.mark.asyncio
async def test_aborted_run_is_reported_as_cancelled_not_completed():
    async with FakeGateway([{"state": "aborted", "message": {"text": "stopped"}}]) as gateway:
        runtime = OpenClawRuntime(gateway.config())
        handle = await runtime.start("do it")
        result = await asyncio.wait_for(collect_result(runtime.events(handle)), timeout=5)

    assert result.status == "cancelled"


@pytest.mark.asyncio
async def test_error_state_is_reported_with_the_gateway_message():
    events = [{"state": "error", "errorMessage": "sandbox is unhealthy"}]
    async with FakeGateway(events) as gateway:
        runtime = OpenClawRuntime(gateway.config())
        handle = await runtime.start("do it")
        result = await asyncio.wait_for(collect_result(runtime.events(handle)), timeout=5)

    assert result.status == "error"
    assert result.summary == "sandbox is unhealthy"


@pytest.mark.asyncio
async def test_events_from_another_run_are_ignored():
    async def stream(runtime, handle):
        return [event.kind async for event in runtime.events(handle)]

    events = [
        # A concurrent run's frames share the socket. This one must not
        # terminate our stream or leak its text into our result.
        {"runId": "someone-else", "state": "final", "message": {"text": "not ours"}},
        {"state": "delta", "message": {"text": "ours"}},
        {"state": "final", "message": {"text": "done"}},
    ]
    async with FakeGateway(events) as gateway:
        runtime = OpenClawRuntime(gateway.config())
        handle = await runtime.start("do it")
        kinds = await asyncio.wait_for(stream(runtime, handle), timeout=5)

    assert kinds == ["text_delta", "completed"]


@pytest.mark.asyncio
async def test_a_dropped_connection_fails_the_run_instead_of_hanging():
    async with FakeGateway([{"state": "delta", "message": {"text": "half an ans"}}]) as gateway:
        runtime = OpenClawRuntime(gateway.config())
        handle = await runtime.start("do it")
        # The socket goes away before any terminal state arrives. Without a
        # sentinel from the reader, events() would park on the queue forever
        # and leave the worker wedged with an active job.
        await handle._connection._ws.close()
        result = await asyncio.wait_for(collect_result(runtime.events(handle)), timeout=5)

    assert result.status == "error"
    assert "closed before the run finished" in result.summary
