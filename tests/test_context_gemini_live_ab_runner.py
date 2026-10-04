import json
import os
import subprocess
import sys


def test_live_gemini_runner_defaults_to_no_send_without_credential() -> None:
    env = dict(os.environ)
    env.pop("GEMINI_API_KEY", None)

    completed = subprocess.run(
        [sys.executable, "scripts/run_gemini_live_ab.py"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 0
    value = json.loads(completed.stdout)
    assert value["status"] == "BLOCKED_SEND_NOT_REQUESTED"
    assert value["required_env"] == "GEMINI_API_KEY"
    assert value["credential_read"] is False
    assert value["network_request_sent"] is False
    assert value["scientific_n_increment"] == 0
    assert value["efficacy_effect"] == "NONE"
    assert value["independent_validation_effect"] == "NONE"
    assert value["high_assurance_effect"] == "NONE"


def test_live_gemini_runner_send_fails_closed_without_credential() -> None:
    env = dict(os.environ)
    env.pop("GEMINI_API_KEY", None)

    completed = subprocess.run(
        [sys.executable, "scripts/run_gemini_live_ab.py", "--send"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 2
    value = json.loads(completed.stdout)
    assert value["status"] == "BLOCKED_TRANSPORT_CREDENTIAL_MISSING"
    assert value["required_env"] == "GEMINI_API_KEY"
    assert value["credential_value_recorded"] is False
    assert value["scientific_n_increment"] == 0
    assert value["efficacy_effect"] == "NONE"


def test_live_gemini_runner_blocks_before_network_without_tokenizer() -> None:
    env = dict(os.environ)
    env["GEMINI_API_KEY"] = "fake-test-key"
    env["PYTHONPATH"] = "src"

    completed = subprocess.run(
        [sys.executable, "-S", "scripts/run_gemini_live_ab.py", "--send"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 4
    value = json.loads(completed.stdout)
    assert value["status"] == "BLOCKED_MEASUREMENT_DEPENDENCY_MISSING"
    assert value["required_dependency"] == "tiktoken==0.14.0"
    assert value["network_request_sent"] is False
    assert value["credential_value_recorded"] is False
