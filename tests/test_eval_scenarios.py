from pathlib import Path

from pipecat.evals.scenario import EvalScenario


def test_eval_scenarios_parse():
    for path in Path("evals/scenarios").glob("*.yaml"):
        scenario = EvalScenario.load(path)
        assert scenario.name
        assert scenario.turns


def test_delegation_eval_asserts_function_call():
    scenario = EvalScenario.load("evals/scenarios/delegates_agent_work.yaml")

    expectations = [expect for turn in scenario.turns for expect in turn.expect]

    assert any(
        expect.event == "function_call"
        and expect.calls
        and expect.calls[0].name == "send_to_agent_loop"
        for expect in expectations
    )
