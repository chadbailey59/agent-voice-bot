"""Reference Pipecat bot with voice and agent loops."""

from __future__ import annotations

import os
import sys
from importlib.util import find_spec

from dotenv import load_dotenv
from loguru import logger
from pipecat.adapters.schemas.direct_function import tool_options
from pipecat.bus.messages import BusJobResponseMessage, BusJobUpdateMessage
from pipecat.evals.transport import EvalTransportParams
from pipecat.frames.frames import (
    FunctionCallResultProperties,
    LLMMessagesAppendFrame,
    LLMRunFrame,
)
from pipecat.pipeline.job_context import JobStatus
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.run import main
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.workers.runner import WorkerRunner

from agent_voice_bot.agent_worker import AgentWorker
from agent_voice_bot.application import build_application_runtime, build_env_feature_registry
from agent_voice_bot.config import (
    AGENT_LOOP_WORKER,
    MAIN_WORKER,
    PLAIN_SPOKEN_OUTPUT_INSTRUCTION,
    AppConfig,
)
from agent_voice_bot.services.speech import default_speech_factory
from agent_voice_bot.services.voice import default_voice_factory

if os.getenv("AGENT_VOICE_SKIP_DOTENV") != "1":
    # override=False so a loaded profile (or anything already exported by the
    # shell) wins; .env only fills in variables that are otherwise unset.
    load_dotenv(override=False)

if find_spec("daily") is not None:
    from pipecat.transports.daily.transport import DailyParams
else:
    DailyParams = None


transport_params = {
    "eval": lambda: EvalTransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
    ),
    # Pipecat's runner maps the "webrtc" transport key to SmallWebRTC.
    "webrtc": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
    ),
}

if DailyParams is not None:
    transport_params["daily"] = lambda: DailyParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
    )


@tool_options(cancel_on_interruption=False, timeout_secs=5)
async def send_to_agent_loop(  # noqa: D417 — `params` is framework plumbing, not tool-schema Args
    params: FunctionCallParams, user_input: str):
    """Forward a user request or follow-up to the agent loop.

    Use this for anything you can't answer immediately yourself: research,
    tool use, multi-step work, code/file/web access, or external agents.
    Use it BOTH to start new agent work and to pass along a follow-up,
    correction, or refinement while agent work is already running — just
    forward what the user said. The agent loop decides whether that input
    starts a new task or steers the running one; you do not.

    After forwarding, say only a very short acknowledgement of one to four
    words, such as "One sec.", "Hang on.", or "On it." Do not add filler,
    status details, or calls to action. Results arrive later and you'll
    relay them.

    Args:
        user_input: What the user wants done or wants to add, preserving
            important details.
    """
    job_id = await params.pipeline_worker.request_job(
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


@tool_options(cancel_on_interruption=False, timeout_secs=5)
async def stop_agent_loop(  # noqa: D417 — `params` is framework plumbing, not tool-schema Args
    params: FunctionCallParams, reason: str):
    """Stop or cancel the agent work currently running in the agent loop.

    Use this when the user wants to abort, cancel, or call off the task the
    agent loop is working on. This is preemptive — it tries to halt the work
    now, not queue another instruction. Whether a given backend can truly
    preempt is backend-specific; if nothing is running, say so.

    Args:
        reason: Why the user wants to stop (brief).
    """
    job_id = await params.pipeline_worker.stop_active_agent_job(reason)
    if job_id is None:
        await params.result_callback(
            {"status": "nothing_running"},
            properties=FunctionCallResultProperties(run_llm=True),
        )
        return
    # The worker replies with a CANCELLED response; narrate from there.
    await params.result_callback(
        {"status": "stopping", "job_id": job_id},
        properties=FunctionCallResultProperties(run_llm=False),
    )


@tool_options(cancel_on_interruption=False)
async def end_conversation(  # noqa: D417 — `params` is framework plumbing, not tool-schema Args
    params: FunctionCallParams, reason: str):
    """End the conversation when the user clearly says goodbye.

    Args:
        reason: Why the conversation is ending.
    """
    await params.pipeline_worker.say_goodbye_and_end(
        reason=reason,
        result_callback=params.result_callback,
    )


class VoiceBotWorker(PipelineWorker):
    """Pipeline worker that is both the media path and the voice loop.

    The inline voice LLM makes exactly one judgment per turn: answer the user
    directly, or forward the input to the agent loop with the tools above. It
    does NOT decide whether a forward starts a new task or refines a running
    one — the agent loop owns that, and all other backend-specific variance.
    This worker keeps a single job handle (learned from the agent loop) so it
    can stop in-flight work and narrate status honestly.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The agent loop's current active task, as reported back to us. Used to
        # target stop_agent_loop and to clear state when work finishes.
        self._active_job_id: str | None = None

    async def stop_active_agent_job(self, reason: str) -> str | None:
        """Cancel the active agent-loop job, returning its id, or None if idle."""
        if self._active_job_id is None:
            return None
        job_id = self._active_job_id
        logger.info(f"Stopping agent-loop job {job_id}: {reason!r}")
        await self.cancel_job_group(job_id, reason=reason)
        return job_id

    async def say_goodbye_and_end(self, *, reason: str, result_callback) -> None:
        """Speak a brief goodbye, resolve the tool call, and end the session."""
        await self.queue_frame(
            LLMMessagesAppendFrame(
                messages=[{"role": "developer", "content": "Say goodbye briefly."}],
                run_llm=True,
            )
        )
        await self.flush_pipeline()
        await result_callback(None, properties=FunctionCallResultProperties(run_llm=False))
        await self.flush_pipeline()
        await self.end(reason=reason)

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
            content = (
                "The agent task was stopped. Tell the user it's cancelled. "
                f"{PLAIN_SPOKEN_OUTPUT_INSTRUCTION}"
            )
        elif message.status != JobStatus.COMPLETED or kind == "error":
            if finished_active:
                self._active_job_id = None
            content = (
                "The agent task did not finish successfully. Tell the user it "
                f"failed (status {message.status}). "
                f"{PLAIN_SPOKEN_OUTPUT_INSTRUCTION}"
            )
        elif kind == "steering":
            # A follow-up reached the agent loop while a task was running.
            if response.get("applied") is False:
                content = (
                    "The user's follow-up reached the agent loop, but this "
                    "backend could not apply it to the active run. Briefly tell "
                    "the user the current task is still running and they may need "
                    f"to stop and resend the update. Backend note: {response.get('status', '')}"
                    f" {PLAIN_SPOKEN_OUTPUT_INSTRUCTION}"
                )
            else:
                content = (
                    "Your follow-up was passed to the running task. Briefly tell "
                    "the user you've added it to what's already in progress. "
                    f"{PLAIN_SPOKEN_OUTPUT_INSTRUCTION}"
                )
        else:  # final result
            if finished_active:
                self._active_job_id = None
            content = (
                "Agent-loop result is ready. Turn it into one concise spoken "
                "answer for the user, keeping any specific codes, numbers, or "
                "names accurate. If the result says it cannot determine the "
                "answer, state that limitation clearly. Do not add a follow-up "
                "question, offer, or call to action. "
                f"{PLAIN_SPOKEN_OUTPUT_INSTRUCTION} "
                f"Result: {response.get('summary', response)}"
            )

        await self.queue_frame(
            LLMMessagesAppendFrame(
                messages=[{"role": "developer", "content": content}],
                run_llm=True,
            )
        )


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    logger.info("Starting agent-voice-bot reference architecture")

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)

    config = AppConfig.from_env()
    speech = default_speech_factory().build(config.speech_provider)
    voice_llm = default_voice_factory().build(config.voice_provider)

    context = LLMContext(tools=[send_to_agent_loop, stop_agent_loop, end_conversation])
    aggregators = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=speech.vad),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            speech.stt,
            aggregators.user(),
            voice_llm,
            speech.tts,
            transport.output(),
            aggregators.assistant(),
        ]
    )

    main_worker = VoiceBotWorker(
        pipeline,
        name=MAIN_WORKER,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected")
        context.add_message(
            {
                "role": "developer",
                "content": (
                    "Greet the user briefly. Say you can answer quick "
                    "questions directly and can start agent work in the background "
                    "when needed."
                ),
            }
        )
        await main_worker.queue_frame(LLMRunFrame())

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await runner.cancel()

    agent_loop_config = config.agent
    logger.info(f"Agent loop backend mode: {agent_loop_config.mode}")
    if agent_loop_config.mode == "nemohermes":
        logger.info(f"NemoHermes base URL: {agent_loop_config.nemohermes_base_url}")

    agent_client = build_application_runtime(config, features=build_env_feature_registry())
    await runner.add_workers(
        AgentWorker(agent_client),
        main_worker,
    )
    await runner.run()


async def bot(runner_args: RunnerArguments):
    """Main bot entry point compatible with Pipecat Cloud."""
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


def cli_main():
    """Console script entry point that keeps Pipecat runner discovery working."""
    sys.modules["__main__"].bot = bot
    main()


if __name__ == "__main__":
    main()
