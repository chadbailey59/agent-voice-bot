"""Reference Pipecat bot with voice and agent loops."""

from __future__ import annotations

import os
import sys
from importlib.util import find_spec

from dotenv import load_dotenv
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.bus import BusBridgeProcessor
from pipecat.evals.transport import EvalTransportParams
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
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.workers.llm import LLMWorkerActivationArgs
from pipecat.workers.runner import WorkerRunner

from agent_voice_bot.config import DEFAULT_CARTESIA_VOICE_ID, VOICE_LOOP_WORKER, MAIN_WORKER
from agent_voice_bot.config import AgentLoopConfig
from agent_voice_bot.agent_loop import AgentLoopClient
from agent_voice_bot.workers import VoiceLoopWorker, AgentLoopWorker

load_dotenv(override=True)

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


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    logger.info("Starting agent-voice-bot reference architecture")

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)

    stt = DeepgramSTTService(api_key=os.environ["DEEPGRAM_API_KEY"])
    tts = CartesiaTTSService(
        api_key=os.environ["CARTESIA_API_KEY"],
        settings=CartesiaTTSService.Settings(
            voice=os.getenv("CARTESIA_VOICE_ID", DEFAULT_CARTESIA_VOICE_ID),
        ),
    )

    context = LLMContext()
    aggregators = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    bridge = BusBridgeProcessor(
        bus=runner.bus,
        worker_name=MAIN_WORKER,
        name=f"{MAIN_WORKER}::BusBridge",
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            aggregators.user(),
            bridge,
            tts,
            transport.output(),
            aggregators.assistant(),
        ]
    )

    main_worker = PipelineWorker(
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
        await main_worker.activate_worker(
            VOICE_LOOP_WORKER,
            args=LLMWorkerActivationArgs(
                messages=[
                    {
                        "role": "developer",
                        "content": (
                            "Greet the user briefly. Say you can answer quick "
                            "questions directly and can start agent work in the background "
                            "when needed."
                        ),
                    },
                ],
            ),
        )

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await runner.cancel()

    agent_loop_config = AgentLoopConfig.from_env()
    logger.info(f"Agent loop backend mode: {agent_loop_config.mode}")
    if agent_loop_config.mode == "nemohermes":
        logger.info(f"NemoHermes base URL: {agent_loop_config.nemohermes_base_url}")

    agent_client = AgentLoopClient(agent_loop_config)
    await runner.add_workers(
        AgentLoopWorker(agent_client),
        VoiceLoopWorker(api_key=os.environ["OPENAI_API_KEY"]),
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
