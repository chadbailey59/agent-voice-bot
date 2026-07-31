"""Live checks against a real OpenClaw Gateway. Opt-in, and they spend tokens.

    export OPENCLAW_LIVE_TESTS=1
    export OPENCLAW_GATEWAY_URL=ws://127.0.0.1:18790
    export OPENCLAW_TOKEN="$(nemoclaw nc gateway-token --quiet)"
    uv run pytest tests/test_live_openclaw.py -v

These pin the Gateway behaviours `openclaw.py` is built on. The default suite's
FakeGateway models all of them, but a fake only ever agrees with whoever wrote
it: every assertion here corresponds to a bug that shipped because the fake and
the code shared the same wrong assumption. Run them after an OpenClaw upgrade.

The opt-in is a separate variable from the gateway URL on purpose — that URL is
a normal thing to have exported while developing, and finding out you had
started billable agent runs by typing `pytest` would be a nasty surprise.
"""

import asyncio
import os

import pytest

from agent_voice_bot.config import OpenClawConfig
from agent_voice_bot.openclaw import OpenClawRuntime, _GatewayConnection, collect_result

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("OPENCLAW_LIVE_TESTS") != "1",
        reason="live Gateway tests are opt-in: set OPENCLAW_LIVE_TESTS=1",
    ),
]

# Long enough to still be running when we interrupt it.
LONG_TASK = "Write a detailed 900-word essay about the history of the bicycle."
# Cheap, and its answer is unmistakable in a transcript.
MARKER = "TRAINS-9"
SHORT_TASK = f"Ignore everything before this. Reply with exactly: {MARKER}"


@pytest.fixture
def config():
    return OpenClawConfig(
        gateway_url=os.getenv("OPENCLAW_GATEWAY_URL", "ws://127.0.0.1:18790"),
        token=os.getenv("OPENCLAW_TOKEN"),
        password=os.getenv("OPENCLAW_PASSWORD"),
        session_key=os.getenv("OPENCLAW_SESSION_KEY", "agent:main:main"),
        timeout_secs=90,
    )


async def _first_token(runtime, handle):
    """Start consuming and return once the agent is demonstrably producing."""
    events = runtime.events(handle)
    async for event in events:
        if event.kind == "text_delta":
            return events
    raise AssertionError("the run ended without producing any output")


@pytest.mark.asyncio
async def test_the_handshake_and_credentials_work(config):
    """First, so a bad token or a down sandbox is obvious rather than a timeout."""
    conn = _GatewayConnection(config)
    await conn.connect()
    hello = conn._hello.result()
    await conn.close()

    assert hello["protocol"] == 4, "openclaw.py negotiates minProtocol/maxProtocol 4"
    assert hello["server"]["version"]


@pytest.mark.asyncio
async def test_abort_reaches_the_gateway_on_a_connection_it_did_not_start(config):
    """stop() dials its own connection because the stream's is already closed.

    Cancellation unwinds events(), whose finally closes the socket, so an abort
    sent on the handle's connection reaches nothing — the agent kept working
    while the user was told it had stopped.
    """
    runtime = OpenClawRuntime(config)
    handle = await runtime.start(LONG_TASK)
    events = await _first_token(runtime, handle)

    await events.aclose()  # what cancellation does: closes the stream connection
    assert await runtime.stop(handle, "live test") is True


@pytest.mark.asyncio
async def test_aborting_a_finished_run_reports_nothing_to_abort(config):
    """`{aborted: false, runIds: []}` is the say-stop-a-moment-too-late race.

    It must not read as a failure, or every such race logs an error and the
    worker treats a benign outcome as a broken Gateway.
    """
    runtime = OpenClawRuntime(config)
    handle = await runtime.start(SHORT_TASK)
    result = await collect_result(runtime.events(handle))
    assert result.status == "completed"

    assert await runtime.stop(handle, "live test") is False


@pytest.mark.asyncio
async def test_a_followup_interrupts_the_run_and_the_stream_follows_it(config):
    """The one that matters most: a follow-up has to produce an answer.

    sessions.steer aborts the running turn and starts a replacement rather than
    merging into it. While the handle stayed on the original run, the abort
    ended the stream, the voice loop told the user their task was cancelled, and
    the run they actually asked for finished with nobody listening.
    """
    runtime = OpenClawRuntime(config)
    handle = await runtime.start(LONG_TASK)
    original = handle.run_id
    events = await _first_token(runtime, handle)

    await runtime.send_followup(handle, SHORT_TASK)
    assert handle.run_id != original, "the handle must move onto the replacement run"

    result = await asyncio.wait_for(collect_result(events), timeout=config.timeout_secs)
    assert result.status == "completed", "a follow-up must not surface as a cancellation"
    assert MARKER in result.summary, "the user must hear the answer to their follow-up"
