import asyncio

import pytest

from agent_voice_bot.agent_worker import AgentWorker
from agent_voice_bot.core import AgentEvent, FollowupResult, RunHandle


class _Message:
    def __init__(self, job_id, payload):
        self.job_id = job_id
        self.payload = payload


class FakeRuntime:
    """An OpenClaw-shaped runtime with no socket behind it."""

    def __init__(self, events=(), *, started=None):
        self.events_to_emit = list(events)
        self.followups: list[tuple[RunHandle, str]] = []
        self.stopped: list[tuple[RunHandle, str | None]] = []
        self.handle = started or RunHandle(run_id="remote-run")
        self.release = asyncio.Event()
        self.release.set()

    async def start(self, user_input):
        self.user_input = user_input
        return self.handle

    async def events(self, handle):
        await self.release.wait()
        for event in self.events_to_emit:
            yield event

    async def send_followup(self, handle, user_input):
        self.followups.append((handle, user_input))
        return FollowupResult(applied=True, status="steered")

    async def stop(self, handle, reason=None):
        self.stopped.append((handle, reason))

    async def close(self):
        return None


def _capture(worker):
    calls = []

    async def capture(job_id, response=None, *, status=None, urgent=False):
        calls.append({"job_id": job_id, "response": response, "status": status, "urgent": urgent})

    return calls, capture


@pytest.mark.asyncio
async def test_forwarded_input_while_busy_steers_the_running_job():
    runtime = FakeRuntime()
    worker = AgentWorker(runtime)
    worker._active_job_id = "job-active"
    worker._active_run_handle = runtime.handle
    responses, worker.send_job_response = _capture(worker)

    await worker.run_agent_loop(_Message("job-followup", {"input": "tighten the scope"}))

    assert runtime.followups == [(runtime.handle, "tighten the scope")]
    assert responses == [
        {
            "job_id": "job-followup",
            "response": {
                "kind": "steering",
                "active_job_id": "job-active",
                "applied": True,
                "status": "steered",
            },
            "status": None,
            "urgent": True,
        }
    ]


@pytest.mark.asyncio
async def test_a_completed_run_reports_its_summary_and_clears_the_active_job():
    runtime = FakeRuntime([AgentEvent("completed", text="ZEBRA-4417")])
    worker = AgentWorker(runtime)
    responses, worker.send_job_response = _capture(worker)
    updates, worker.send_job_update = _capture(worker)

    await worker.run_agent_loop(_Message("job-1", {"input": "do it"}))

    # The voice loop learns the cancellable handle from this update.
    assert updates[0]["response"] == {"kind": "started", "backend_run_id": "remote-run"}
    assert responses[0]["response"] == {
        "kind": "final",
        "status": "completed",
        "summary": "ZEBRA-4417",
    }
    assert worker._active_job_id is None
    assert worker._active_run_handle is None


@pytest.mark.asyncio
async def test_cancelling_an_in_flight_run_stops_the_backend():
    runtime = FakeRuntime([AgentEvent("completed", text="never gets here")])
    runtime.release.clear()
    worker = AgentWorker(runtime)
    _, worker.send_job_response = _capture(worker)
    _, worker.send_job_update = _capture(worker)

    task = asyncio.create_task(worker.run_agent_loop(_Message("job-1", {"input": "do it"})))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert runtime.stopped == [(runtime.handle, "Cancelled by the voice loop.")]
    assert worker._active_job_id is None


@pytest.mark.asyncio
async def test_a_backend_failure_is_reported_rather_than_swallowed():
    class Broken(FakeRuntime):
        async def start(self, user_input):
            raise RuntimeError("gateway refused the connection")

    worker = AgentWorker(Broken())
    responses, worker.send_job_response = _capture(worker)

    await worker.run_agent_loop(_Message("job-1", {"input": "do it"}))

    assert responses[0]["response"]["kind"] == "error"
    assert "gateway refused" in responses[0]["response"]["error"]
    assert worker._active_job_id is None
