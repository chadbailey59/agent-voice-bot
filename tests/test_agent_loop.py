import pytest

from agent_voice_bot.config import AgentLoopConfig
from agent_voice_bot.agent_loop import AgentLoopClient, AgentLoopRequest


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
