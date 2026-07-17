---
name: nvidia-riva-speech
description: Deploy and configure the local NVIDIA speech stack for agent-voice-bot — Parakeet ASR and Magpie TTS on self-hosted Riva NIMs, selected with SPEECH_PROVIDER=nvidia-riva. Use when setting up local speech, choosing a Parakeet NIM, changing a TTS voice, or debugging a NIM that exits at startup.
---

# Local NVIDIA speech (Riva NIMs)

`SPEECH_PROVIDER=nvidia-riva` keeps audio on the machine by talking gRPC to two
self-hosted [NVIDIA Riva NIM](https://docs.nvidia.com/nim/riva/asr/latest/getting-started.html)
containers. The alternative is the hosted default, `deepgram-cartesia`
(Deepgram STT + Cartesia TTS), which needs API keys.

| Provider | STT | TTS | Runs |
| --- | --- | --- | --- |
| `deepgram-cartesia` (default) | Deepgram | Cartesia | Hosted, needs API keys |
| `nvidia-riva` | Parakeet | Magpie | Local, on your own GPU |

Speech is selected independently of the voice-loop and agent-loop models.

## Before you start: check the host

Self-hosting a NIM is covered by the NVIDIA AI Enterprise License, free for
development through the NVIDIA Developer Program. It needs an NVIDIA GPU of
compute capability 8.0 or higher; GeForce RTX 40xx and 50xx qualify alongside
the datacenter cards.

On an RTX 5090 the pair resides in about 17 GB of VRAM, measured at 4 GB for
Parakeet and 13 GB for Magpie. Both load their models at startup and hold that
memory, so **a card already hosting a local LLM may not fit all three**. Check
free VRAM with `nvidia-smi` before deploying, and stop the local LLM first if
the card is shared (see the `nemotron-local-llm` skill).

You also need an `NGC_API_KEY` from [ngc.nvidia.com](https://ngc.nvidia.com).

## Pick an ASR NIM that can stream

**Not every Parakeet NIM can stream, and the wrong one fails at runtime rather
than at deploy time.** `parakeet-0.6b-tdt` ships only `mode=ofl` (offline)
profiles and cannot serve this pipeline. `parakeet-1-1b-ctc-en-us` offers
`mode=str`, and that is what the bot expects.

Parakeet is the streaming member of NVIDIA's ASR family and is built for
latency, which is what the voice loop needs. Its sibling Canary is more
accurate but segmented, so it does not stream.

## Deploy the NIMs

```bash
export NGC_API_KEY=nvapi-...   # from ngc.nvidia.com

docker run -d --name parakeet-asr --gpus all --shm-size=8GB \
  -e NGC_API_KEY -e NIM_TAGS_SELECTOR="mode=str,diarizer=disabled,vad=default" \
  -p 50051:50051 -p 9000:9000 -v ~/.cache/nim:/opt/nim/.cache \
  nvcr.io/nim/nvidia/parakeet-1-1b-ctc-en-us:latest

docker run -d --name magpie-tts --gpus all --shm-size=8GB \
  -e NGC_API_KEY \
  -p 50052:50051 -p 9001:9000 -v ~/.cache/nim:/opt/nim/.cache \
  nvcr.io/nim/nvidia/magpie-tts-multilingual:latest
```

Each NIM serves gRPC on 50051 inside its own container, hence the remapped TTS
host port.

Both images are roughly 25 GB, and the first start downloads a model profile
and builds TensorRT engines. Allow **15-25 minutes** before readiness:

```bash
curl localhost:9000/v1/health/ready   # ASR
curl localhost:9001/v1/health/ready   # TTS
```

## Point the bot at them

```bash
cd bot
uv sync --extra nvidia
echo "SPEECH_PROVIDER=nvidia-riva" >> .env
```

```dotenv
SPEECH_PROVIDER=nvidia-riva
NVIDIA_ASR_SERVER=localhost:50051
NVIDIA_TTS_SERVER=localhost:50052
```

No API key is involved, because a local NIM authenticates nothing.

## Models and voices

Riva binds the acoustic model when the container starts, through `CONTAINER_ID`
and `NIM_TAGS_SELECTOR`, and the client sends an empty model name. So
`NVIDIA_ASR_MODEL` and `NVIDIA_TTS_MODEL` **only label metrics and logs** —
editing them does not switch models. To swap Parakeet for another ASR model, or
Magpie for `fastpitch-hifigan-en-us`, redeploy the NIM.

`NVIDIA_TTS_VOICE` does take effect at runtime and must name a voice the
deployed TTS model actually serves. It defaults to
`Magpie-Multilingual.EN-US.Aria`, which the default TTS model serves; a
`fastpitch-hifigan-en-us` NIM serves different voices and needs an explicit
name. List what is available:

```bash
curl localhost:9001/v1/audio/list_voices
```

## Remote or NVCF endpoints

To reach a remote endpoint instead of a local NIM, enable TLS and supply a key.
For NVIDIA Cloud Functions, also set the TTS function ID to the NVCF UUID:

```dotenv
NVIDIA_API_KEY=
NVIDIA_ASR_USE_SSL=false
NVIDIA_TTS_USE_SSL=false
NVIDIA_TTS_FUNCTION_ID=
```

The full variable list is in [`bot/.env.example`](../../bot/.env.example).

## Troubleshooting

**ASR NIM exits with status 0 shortly after start, log full of `illegal memory
access`.** This is the out-of-VRAM failure mode, and it misreports itself. Give
the ASR NIM room *before* it starts. When too little VRAM is free, it builds its
TensorRT engines successfully and only then fails to create the execution
context, reporting `CUDA error 2 creating stream for constant data`. Triton
exits, the container follows with status 0, and the log fills with `illegal
memory access` noise from the teardown rather than the allocation failure
itself. Free VRAM and restart the container.

**Runtime ASR failure with a deployed, healthy NIM.** Check the ASR NIM ships a
streaming profile — `parakeet-0.6b-tdt` does not. Redeploy with
`parakeet-1-1b-ctc-en-us` and `NIM_TAGS_SELECTOR=mode=str`.

**A TTS voice name is rejected.** The deployed model must actually serve it;
confirm against `curl localhost:9001/v1/audio/list_voices`.
