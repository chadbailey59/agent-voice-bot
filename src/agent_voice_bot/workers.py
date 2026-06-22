"""Pipecat workers for the reference architecture."""

from __future__ import annotations

import asyncio

from loguru import logger

from pipecat.bus.messages import BusJobRequestMessage, BusJobResponseMessage, BusJobUpdateMessage
from pipecat.frames.frames import FunctionCallResultProperties, LLMMessagesAppendFrame
from pipecat.pipeline.job_context import JobStatus
from pipecat.pipeline.job_decorator import job
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.openai.responses.llm import OpenAIResponsesLLMService
from pipecat.workers.base_worker import BaseWorker
from pipecat.workers.llm import LLMWorker, tool

from agent_voice_bot.config import (
    VOICE_LOOP_MODEL,
    VOICE_LOOP_REASONING_EFFORT,
    VOICE_LOOP_SYSTEM_PROMPT,
    AGENT_LOOP_WORKER,
)
from agent_voice_bot.agent_loop import AgentLoopClient, AgentLoopRequest


class VoiceLoopWorker(LLMWorker):
    """Voice LLM worker that forwards agent work to the agent loop.

    The voice loop makes exactly one judgment: answer the user directly, or
    forward the input to the agent loop. It does NOT decide whether a forward
    starts a new task or refines a running one — the agent loop owns that, and
    all other backend-specific variance. The voice loop keeps a single job
    handle (learned from the agent loop) so it can stop in-flight work and
    narrate status honestly.
    """

    def __init__(self, *, api_key: str):
        llm = OpenAIResponsesLLMService(
            api_key=api_key,
            settings=OpenAIResponsesLLMService.Settings(
                model=VOICE_LOOP_MODEL,
                system_instruction=VOICE_LOOP_SYSTEM_PROMPT,
                extra={"reasoning": {"effort": VOICE_LOOP_REASONING_EFFORT}},
            ),
        )
        super().__init__("voice-loop", llm=llm, bridged=())
        # The agent loop's current active task, as reported back to us. Used to
        # target stop_agent_loop and to clear state when work finishes.
        self._active_job_id: str | None = None

    @tool(cancel_on_interruption=False, timeout_secs=5)
    async def send_to_agent_loop(self, params: FunctionCallParams, user_input: str):
        """Forward a user request or follow-up to the agent loop.

        Use this for anything you can't answer immediately yourself: research,
        tool use, multi-step work, code/file/web access, or external agents.
        Use it BOTH to start new agent work and to pass along a follow-up,
        correction, or refinement while agent work is already running — just
        forward what the user said. The agent loop decides whether that input
        starts a new task or steers the running one; you do not.

        After forwarding, briefly tell the user you're on it and stay available
        for more input. Results arrive later and you'll relay them.

        Args:
            user_input: What the user wants done or wants to add, preserving
                important details.
        """
        job_id = await self.request_job(
            AGENT_LOOP_WORKER,
            name="run",
            payload={"input": user_input},
            timeout=None,
        )
        logger.info(f"Forwarded to agent loop as job {job_id}: {user_input!r}")
        await params.result_callback(
            {"status": "sent"},
            properties=FunctionCallResultProperties(run_llm=True),
        )

    @tool(cancel_on_interruption=False, timeout_secs=5)
    async def stop_agent_loop(self, params: FunctionCallParams, reason: str):
        """Stop or cancel the agent work currently running in the agent loop.

        Use this when the user wants to abort, cancel, or call off the task the
        agent loop is working on. This is preemptive — it tries to halt the work
        now, not queue another instruction. Whether a given backend can truly
        preempt is backend-specific; if nothing is running, say so.

        Args:
            reason: Why the user wants to stop (brief).
        """
        if self._active_job_id is None:
            await params.result_callback(
                {"status": "nothing_running"},
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return

        job_id = self._active_job_id
        logger.info(f"Stopping agent-loop job {job_id}: {reason!r}")
        await self.cancel_job_group(job_id, reason=reason)
        # The worker replies with a CANCELLED response; narrate from there.
        await params.result_callback(
            {"status": "stopping", "job_id": job_id},
            properties=FunctionCallResultProperties(run_llm=False),
        )

    @tool(cancel_on_interruption=False)
    async def end_conversation(self, params: FunctionCallParams, reason: str):
        """End the conversation when the user clearly says goodbye.

        Args:
            reason: Why the conversation is ending.
        """
        await self.end(
            reason=reason,
            messages=[{"role": "developer", "content": "Say goodbye briefly."}],
            result_callback=params.result_callback,
        )

    async def on_job_update(self, message: BusJobUpdateMessage) -> None:
        await super().on_job_update(message)
        if message.source != AGENT_LOOP_WORKER:
            return
        update = message.update or {}
        if update.get("kind") == "started":
            # The agent loop accepted this as the active, cancellable task.
            # The send tool already acked verbally, so just record the handle.
            self._active_job_id = message.job_id
            logger.info(f"Agent loop started job {message.job_id}")

    async def on_job_response(self, message: BusJobResponseMessage) -> None:
        await super().on_job_response(message)
        if message.source != AGENT_LOOP_WORKER:
            return

        response = message.response or {}
        kind = response.get("kind")
        finished_active = message.job_id == self._active_job_id

        if message.status == JobStatus.CANCELLED:
            if finished_active:
                self._active_job_id = None
            content = "The agent task was stopped. Tell the user it's cancelled."
        elif message.status != JobStatus.COMPLETED or kind == "error":
            if finished_active:
                self._active_job_id = None
            content = (
                "The agent task did not finish successfully. Tell the user it "
                f"failed (status {message.status})."
            )
        elif kind == "steering":
            # A follow-up reached the agent loop while a task was running.
            content = (
                "Your follow-up was passed to the running task. Briefly tell "
                "the user you've added it to what's already in progress."
            )
        else:  # final result
            if finished_active:
                self._active_job_id = None
            content = (
                "Agent-loop result is ready. Summarize it for the user in a "
                "brief spoken response, keeping any specific codes, numbers, or "
                f"names accurate: {response.get('summary', response)}"
            )

        await self.queue_frame(
            LLMMessagesAppendFrame(
                messages=[{"role": "developer", "content": content}],
                run_llm=True,
            ),
            FrameDirection.DOWNSTREAM,
        )


class AgentLoopWorker(BaseWorker):
    """Bus worker that owns agent-loop state and routes forwarded input.

    It decides whether forwarded input starts a new task or steers the one
    already running, runs the work through a backend adapter, and supports
    preemptive cancellation. All backend-specific variance lives here; the
    voice loop just forwards.
    """

    def __init__(self, client: AgentLoopClient):
        super().__init__(AGENT_LOOP_WORKER)
        self._client = client
        self._active_job_id: str | None = None

    @job(name="run")
    async def run_agent_loop(self, message: BusJobRequestMessage) -> None:
        payload = message.payload or {}
        user_input = str(payload.get("input", ""))

        # Already busy: this input refines the running task rather than starting
        # a new one. A real backend decides how to apply it (live injection,
        # cancel-and-restart, queue, or not at all). The reference simply
        # acknowledges receipt and lets the active task keep running.
        if self._active_job_id is not None:
            logger.info(
                f"Agent loop busy ({self._active_job_id}); treating job "
                f"{message.job_id} as steering: {user_input!r}"
            )
            await self.send_job_response(
                message.job_id,
                {"kind": "steering", "active_job_id": self._active_job_id},
                urgent=True,
            )
            return

        self._active_job_id = message.job_id
        # Tell the voice loop which job is now the cancellable active task.
        await self.send_job_update(message.job_id, {"kind": "started"}, urgent=True)

        request = AgentLoopRequest(
            user_request=user_input,
            reason="Forwarded from the voice loop.",
        )
        try:
            result = await self._client.run(request)
        except asyncio.CancelledError:
            # Cancelled by stop_agent_loop; the bus cancel path replies CANCELLED.
            self._active_job_id = None
            raise
        except Exception as exc:
            logger.exception(f"Agent-loop job failed: {exc}")
            self._active_job_id = None
            await self.send_job_response(
                message.job_id,
                {"kind": "error", "error": str(exc)},
                status=JobStatus.ERROR,
                urgent=True,
            )
            return

        self._active_job_id = None
        # Deliver urgently so the finished result preempts queued bus traffic
        # and the voice loop can speak it promptly.
        await self.send_job_response(
            message.job_id,
            {"kind": "final", "status": result.status, "summary": result.summary},
            urgent=True,
        )
