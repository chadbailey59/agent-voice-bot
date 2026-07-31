import asyncio
import json
import subprocess
import sys

import pytest
import websockets

from agent_voice_bot.config import AGENT_LOOP_INSTRUCTION, OpenClawConfig
from agent_voice_bot.openclaw import OpenClawRuntime, collect_result


def test_the_gateway_client_does_not_depend_on_pipecat():
    """The one thing that makes openclaw.py worth keeping out of agent_worker.py.

    The dependency runs one way: the worker adapts runs and events onto the
    Pipecat bus, and nothing about the wire protocol knows the bus exists. That
    is why these tests can drive a real websocket server without any media
    machinery. A subprocess, because the rest of the suite has Pipecat imported
    long before this runs.
    """
    probe = (
        "import sys; import agent_voice_bot.openclaw; "
        "print(any(m.startswith('pipecat') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False", "openclaw.py pulled in Pipecat"

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

    def __init__(self, chat_events=(), steered_events=()):
        self.methods: list[str] = []
        self.params: dict[str, dict] = {}
        self.chat_events = list(chat_events)
        self.steered_events = list(steered_events)
        self._live_run = ""
        self._clients: list = []
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
        self._clients.append(websocket)
        await websocket.send(
            json.dumps({"type": "event", "event": "connect.challenge", "payload": {"nonce": "n"}})
        )
        try:
            async for raw in websocket:
                frame = json.loads(raw)
                method = frame["method"]
                self.methods.append(method)
                self.params[method] = frame.get("params") or {}
                await websocket.send(json.dumps(self._response(frame)))
                if method == "chat.send":
                    await self._emit(frame["params"]["idempotencyKey"], self.chat_events)
                elif method == "sessions.steer":
                    # The interrupted run's abort and the replacement's output
                    # both follow, in that order, as the live Gateway sends them.
                    await self._emit(self._live_run, [{"state": "aborted"}])
                    await self._emit(frame["params"]["idempotencyKey"], self.steered_events)
        finally:
            self._clients.remove(websocket)

    async def _emit(self, run_id, events):
        """Broadcast to every connection, which is what the live Gateway does.

        A run's frames reach connections that did not start it — that is what
        lets a follow-up be steered from its own socket while the stream
        connection keeps receiving the replacement run's output.
        """
        self._live_run = run_id
        for event in events:
            payload = json.dumps(
                {"type": "event", "event": "chat", "payload": {"runId": run_id, **event}}
            )
            for client in list(self._clients):
                await client.send(payload)

    def _response(self, frame):
        method = frame["method"]
        if method == "connect":
            payload = HELLO_OK
        elif method == "chat.send":
            payload = {"runId": frame["params"]["idempotencyKey"], "status": "started"}
        elif method == "sessions.steer":
            # v2026.5.22 does not merge the follow-up into the running turn: it
            # aborts that run and starts a new one under the idempotency key.
            payload = {
                "runId": frame["params"]["idempotencyKey"],
                "status": "started",
                "messageSeq": 2,
                "interruptedActiveRun": True,
            }
        elif method == "chat.abort":
            # Shape observed from OpenClaw v2026.5.22 aborting a live run.
            payload = {"ok": True, "aborted": True, "runIds": [frame["params"]["runId"]]}
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

        # send_followup and stop() each dial their own connection.
        assert gateway.methods == [
            "connect", "chat.send",
            "connect", "sessions.steer",
            "connect", "chat.abort",
        ]
        assert gateway.params["connect"]["minProtocol"] == 4
        assert gateway.params["connect"]["maxProtocol"] == 4
        assert gateway.params["chat.send"]["sessionKey"] == "agent:main:voice:test"
        assert gateway.params["sessions.steer"]["message"] == "add this detail"
        assert gateway.params["chat.abort"]["runId"] == handle.run_id


@pytest.mark.asyncio
async def test_a_followup_redirects_the_stream_onto_the_steered_run():
    """The user must hear the answer to their follow-up, not "cancelled".

    sessions.steer aborts the running turn and starts a replacement. If the
    handle stayed on the original run, the abort would end the stream,
    collect_result would report `cancelled`, the voice loop would tell the user
    their task was stopped — and the steered run would finish unwatched, so the
    answer they actually asked for would never be spoken.
    """
    async with FakeGateway(
        chat_events=[{"state": "delta", "message": {"text": "bicycles"}}],
        steered_events=[{"state": "final", "message": {"text": "TRAINS-9"}}],
    ) as gateway:
        runtime = OpenClawRuntime(gateway.config())
        handle = await runtime.start("essay about bicycles")
        original = handle.run_id

        events = runtime.events(handle)
        assert (await anext(events)).kind == "text_delta"

        await runtime.send_followup(handle, "make it about trains")
        assert handle.run_id != original, "handle must move onto the replacement run"

        result = await asyncio.wait_for(collect_result(events), timeout=5)

    assert result.status == "completed"
    assert result.summary == "TRAINS-9"


@pytest.mark.asyncio
async def test_a_followup_uses_its_own_connection():
    """The stream connection may be mid-close when a follow-up lands: the run
    just ended, its reader has stopped, and a request on that socket would wait
    for a reply that can never be routed."""
    async with FakeGateway() as gateway:
        runtime = OpenClawRuntime(gateway.config())
        handle = await runtime.start("do it")
        await runtime.send_followup(handle, "and this")

    assert gateway.methods == ["connect", "chat.send", "connect", "sessions.steer"]


@pytest.mark.asyncio
async def test_stop_reports_that_a_finished_run_had_nothing_to_abort():
    """v2026.5.22 answers a finished or unknown run with aborted:false, runIds:[].

    That is the race where the user says "stop" just after the agent finished.
    It is not a Gateway failure, so it must not raise — a real failure arrives
    as ok:false and is raised by request() instead.
    """

    class NothingRunningGateway(FakeGateway):
        def _response(self, frame):
            response = super()._response(frame)
            if frame["method"] == "chat.abort":
                response["payload"] = {"ok": True, "aborted": False, "runIds": []}
            return response

    async with NothingRunningGateway() as gateway:
        runtime = OpenClawRuntime(gateway.config())
        handle = await runtime.start("do it")

        assert await runtime.stop(handle, "cancelled") is False


@pytest.mark.asyncio
async def test_stop_confirms_when_a_run_was_actually_aborted():
    async with FakeGateway() as gateway:
        runtime = OpenClawRuntime(gateway.config())
        handle = await runtime.start("do it")

        assert await runtime.stop(handle, "cancelled") is True


@pytest.mark.asyncio
async def test_a_malformed_abort_response_is_an_error():
    class MalformedGateway(FakeGateway):
        def _response(self, frame):
            response = super()._response(frame)
            if frame["method"] == "chat.abort":
                response["payload"] = "not a dict"
            return response

    async with MalformedGateway() as gateway:
        runtime = OpenClawRuntime(gateway.config())
        handle = await runtime.start("do it")

        with pytest.raises(RuntimeError, match="Unexpected chat.abort response"):
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
