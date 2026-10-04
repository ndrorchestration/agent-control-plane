import json
import os
import subprocess
import sys


def test_live_gemini_runner_fails_closed_without_credential() -> None:
    env = dict(os.environ)
    env.pop("GEMINI_API_KEY", None)

    completed = subprocess.run(
        [sys.executable, "scripts/run_gemini_live_ab.py"],
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
