from agent_control_plane.evaluation import run_evaluation, smoke_cases


def test_smoke_evaluation_cases_pass():
    results = run_evaluation(smoke_cases())
    assert results
    assert all(result.passed for result in results)
