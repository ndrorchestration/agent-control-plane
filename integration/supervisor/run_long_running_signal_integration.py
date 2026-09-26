"""Parent harness for real OS-signal long-running supervisor integration."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def run_case(sig, reason: str) -> None:
    script = Path(__file__).with_name(
        "experimental_long_running_service.py"
    )
    process = subprocess.Popen(
        [
            sys.executable,
            str(script),
            "--interval",
            "0.05",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines: list[str] = []
    try:
        deadline = time.monotonic() + 15
        ready = False
        while time.monotonic() < deadline:
            line = process.stdout.readline()
            if line:
                lines.append(line)
                if "LONG_RUNNING_READY=1" in line:
                    ready = True
                    break
            if process.poll() is not None:
                break
        if not ready:
            raise RuntimeError(
                "long-running supervisor did not reach ready state:\n"
                + "".join(lines)
            )

        os.kill(process.pid, sig)
        output, _ = process.communicate(timeout=15)
        lines.append(output)
        text = "".join(lines)

        required = (
            "LONG_RUNNING_FINAL_STATE=stopped",
            f"LONG_RUNNING_STOP_REASON={reason}",
            "LONG_RUNNING_CHILD_RUNNING=0",
            "LONG_RUNNING_CHECKPOINT_STATE=stopped",
            "LONG_RUNNING_RUNTIME_GENERATION=1",
            "LONG_RUNNING_SERVICE_LEASE_RELEASED=1",
        )
        missing = [item for item in required if item not in text]
        if process.returncode != 0 or missing:
            raise RuntimeError(
                "long-running supervisor signal case failed\n"
                f"signal={sig}\n"
                f"returncode={process.returncode}\n"
                f"missing={missing}\n"
                f"output:\n{text}"
            )
        print(
            f"LONG_RUNNING_SIGNAL_CASE={reason}:PASS",
            flush=True,
        )
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def main() -> None:
    run_case(signal.SIGTERM, "signal_term")
    run_case(signal.SIGINT, "signal_int")
    print("EXPERIMENTAL_LONG_RUNNING_SUPERVISOR=PASS", flush=True)


if __name__ == "__main__":
    main()
