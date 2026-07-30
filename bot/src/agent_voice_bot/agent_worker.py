"""Agent-loop Pipecat worker."""

from __future__ import annotations

import asyncio

from loguru import logger
from pipecat.bus.messages import BusJobRequestMessage
from pipecat.pipeline.job_context import JobStatus
from pipecat.pipeline.job_decorator import job
from pipecat.workers.base_worker import BaseWorker

from agent_voice_bot.config import AGENT_LOOP_WORKER
from agent_voice_bot.core import AgentRuntime, RunHandle, collect_result


class AgentWorker(BaseWorker):
    """Bus worker that owns agent-loop state and routes forwarded input.

    It decides whether forwarded input starts a new task or steers the one
    already running, runs the work through a backend adapter, and supports
    preemptive cancellation. All backend-specific variance lives here; the
    voice loop just forwards.
    """

    def __init__(self, client: AgentRuntime):
        super().__init__(AGENT_LOOP_WORKER)
        self._client = client
        self._active_job_id: str | None = None
        self._active_run_handle: RunHandle | None = None

    @job(name="run")
    async def run_agent_loop(self, message: BusJobRequestMessage) -> None:
        payload = message.payload or {}
        user_input = str(payload.get("input", ""))

        # Already busy: this input refines the running task rather than starting
        # a new one. OpenClaw steers the live run, so this reaches the agent
        # mid-task instead of queueing behind it.
        if self._active_job_id is not None:
            logger.info(
                f"Agent loop busy ({self._active_job_id}); treating job "
                f"{message.job_id} as steering: {user_input!r}"
            )
            followup = None
            if self._active_run_handle is not None:
                followup = await self._client.send_followup(self._active_run_handle, user_input)
            await self.send_job_response(
                message.job_id,
                {
                    "kind": "steering",
                    "active_job_id": self._active_job_id,
                    "applied": followup.applied if followup else False,
                    "status": followup.status if followup else "No active backend run handle yet.",
                },
                urgent=True,
            )
            return

        self._active_job_id = message.job_id

        handle: RunHandle | None = None
        try:
            handle = await self._client.start(user_input)
            self._active_run_handle = handle
            # Tell the voice loop which job is now the cancellable active task.
            await self.send_job_update(
                message.job_id,
                {"kind": "started", "backend_run_id": handle.run_id},
                urgent=True,
            )
            result = await collect_result(self._client, handle)
        except asyncio.CancelledError:
            # Cancelled by stop_agent_loop; the bus cancel path replies CANCELLED.
            if handle is not None:
                await self._client.stop(handle, "Cancelled by the voice loop.")
            self._active_job_id = None
            self._active_run_handle = None
            raise
        except Exception as exc:
            logger.exception(f"Agent-loop job failed: {exc}")
            self._active_job_id = None
            self._active_run_handle = None
            await self.send_job_response(
                message.job_id,
                {"kind": "error", "error": str(exc)},
                status=JobStatus.ERROR,
                urgent=True,
            )
            return

        self._active_job_id = None
        self._active_run_handle = None
        # Deliver urgently so the finished result preempts queued bus traffic
        # and the voice loop can speak it promptly.
        await self.send_job_response(
            message.job_id,
            {"kind": "final", "status": result.status, "summary": result.summary},
            urgent=True,
        )
