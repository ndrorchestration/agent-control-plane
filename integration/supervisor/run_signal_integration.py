"""Send real OS stop signals to the finite ACP supervisor integration process."""

from __future__ import annotations

from pathlib import Path
import signal
import subprocess
import sys
import time


def run_case(signal_value: int, expected_reason: str) -> None:
    script = Path(__file__).with_name("finite_signal_service.py")
    process = subprocess.Popen(
        [
            sys.executable,
            str(script),
            "--max-cycles",
            "200",
            "--interval",
            "0.05",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    lines: list[str] = []
    deadline = time.monotonic() + 10
    ready = False
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        if process.stdout is None:
            break
        line = process.stdout.readline()
        if line:
            lines.append(line.rstrip())
            if line.strip() == "SUPERVISOR_SIGNAL_READY=1":
                ready = True
                break

    if not ready:
        process.kill()
        remainder, _ = process.communicate(timeout=5)
        raise RuntimeError(
            "supervisor did not become ready: "
            + "\n".join(lines)
            + remainder
        )

    process.send_signal(signal_value)
    output, _ = process.communicate(timeout=10)
    lines.extend(output.splitlines())

    if process.returncode != 0:
        raise RuntimeError(
            f"supervisor exited {process.returncode}:\n"
            + "\n".join(lines)
        )

    required = {
        "SUPERVISOR_FINAL_STATE=stopped",
        f"SUPERVISOR_STOP_REASON={expected_reason}",
        "SUPERVISOR_CHILD_RUNNING=0",
    }
    missing = required.difference(lines)
    if missing:
        raise RuntimeError(
            "missing expected supervisor evidence "
            f"{sorted(missing)} from:\n" + "\n".join(lines)
        )

    print(
        f"SUPERVISOR_OS_SIGNAL_CASE={expected_reason}:PASS",
        flush=True,
    )


def main() -> None:
    run_case(signal.SIGTERM, "signal_term")
    run_case(signal.SIGINT, "signal_int")
    print("SUPERVISOR_OS_SIGNAL_INTEGRATION=PASS", flush=True)


if __name__ == "__main__":
    main()
