"""Finite supervisor process used only for real OS-signal integration."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import sys
import tempfile

from agent_control_plane.process_monitor import (
    DurableProcessFailureStore,
    ProcessMonitorTick,
)
from agent_control_plane.process_monitor_cadence import (
    DurableProcessMonitorCadenceStore,
    ProcessMonitorCadencePolicy,
    ScheduledProcessMonitor,
)
from agent_control_plane.process_runtime import (
    ManagedProcessController,
    ManagedProcessSpec,
)
from agent_control_plane.process_supervision import ProcessSupervisionPolicy
from agent_control_plane.supervisor_service import (
    SupervisorServiceContract,
    SupervisorWorkerRegistration,
)
from agent_control_plane.supervisor_service_runner import (
    BoundedSupervisorServiceRunner,
    SupervisorWorkerRuntime,
)
from agent_control_plane.supervisor_signal import SupervisorSignalLatch


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-cycles", type=int, default=200)
    parser.add_argument("--interval", type=float, default=0.05)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="acp-supervisor-signal-") as tmp:
        root = Path(tmp)
        registration = SupervisorWorkerRegistration(
            worker_id="relay-a",
            process_id="relay-a-process",
            ownership_token="relay-a-owner",
        )
        controller = ManagedProcessController(
            ManagedProcessSpec(
                process_id=registration.process_id,
                argv=(
                    sys.executable,
                    "-c",
                    "import time; time.sleep(30)",
                ),
            )
        )
        monitor = ProcessMonitorTick(
            controller=controller,
            policy=ProcessSupervisionPolicy(
                max_restarts=1,
                min_restart_interval_seconds=0,
            ),
            failure_store=DurableProcessFailureStore(
                root / "failure.sqlite3"
            ),
        )
        scheduler = ScheduledProcessMonitor(
            monitor_tick=monitor,
            cadence_store=DurableProcessMonitorCadenceStore(
                root / "cadence.sqlite3"
            ),
            cadence_policy=ProcessMonitorCadencePolicy(
                min_interval_seconds=max(args.interval, 0.01),
            ),
        )
        runtime = SupervisorWorkerRuntime(
            registration=registration,
            controller=controller,
            scheduler=scheduler,
        )
        contract = SupervisorServiceContract(
            service_id="signal-integration",
            workers=(registration,),
        )

        with SupervisorSignalLatch() as latch:
            print("SUPERVISOR_SIGNAL_READY=1", flush=True)
            runner = BoundedSupervisorServiceRunner(
                contract=contract,
                workers=(runtime,),
                max_cycles=args.max_cycles,
                interval_seconds=args.interval,
                now_provider=utc_now,
                sleep_fn=__import__("time").sleep,
                signal_provider=lambda index: latch.signal_name(),
                terminate_timeout_seconds=2,
            )
            report = runner.run()

        print(
            f"SUPERVISOR_FINAL_STATE={report.final_snapshot.state.value}",
            flush=True,
        )
        print(
            "SUPERVISOR_STOP_REASON="
            f"{report.final_snapshot.stop_reason.value}",
            flush=True,
        )
        print(
            "SUPERVISOR_CHILD_RUNNING="
            f"{int(report.final_observations[0].running)}",
            flush=True,
        )


if __name__ == "__main__":
    main()
