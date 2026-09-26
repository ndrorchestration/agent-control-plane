"""Finite integration process proving real OS signal-driven supervisor shutdown."""

from __future__ import annotations

from datetime import datetime, timezone
import argparse
from pathlib import Path
import sys
import tempfile
import time

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
from agent_control_plane.supervisor_signal import (
    InstalledSupervisorSignalHandlers,
    SupervisorSignalLatch,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def worker(root: Path, worker_id: str) -> SupervisorWorkerRuntime:
    process_id = f"{worker_id}-process"
    controller = ManagedProcessController(
        ManagedProcessSpec(
            process_id=process_id,
            argv=(
                sys.executable,
                "-c",
                "import time; time.sleep(120)",
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
            root / f"{worker_id}-failure.sqlite3"
        ),
    )
    scheduler = ScheduledProcessMonitor(
        monitor_tick=monitor,
        cadence_store=DurableProcessMonitorCadenceStore(
            root / f"{worker_id}-cadence.sqlite3"
        ),
        cadence_policy=ProcessMonitorCadencePolicy(
            min_interval_seconds=0.2,
        ),
    )
    registration = SupervisorWorkerRegistration(
        worker_id=worker_id,
        process_id=process_id,
        ownership_token=f"owner-{worker_id}",
    )
    return SupervisorWorkerRuntime(
        registration=registration,
        controller=controller,
        scheduler=scheduler,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-cycles", type=int, default=200)
    parser.add_argument("--interval", type=float, default=0.05)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="acp-signal-supervisor-") as tmp:
        root = Path(tmp)
        workers = (
            worker(root, "relay-a"),
            worker(root, "relay-b"),
        )
        contract = SupervisorServiceContract(
            service_id="acp-signal-supervisor",
            workers=tuple(w.registration for w in workers),
        )
        latch = SupervisorSignalLatch()
        announced_running = False

        def signal_provider(index: int):
            nonlocal announced_running
            if not announced_running:
                announced_running = True
                print("SUPERVISOR_RUNNING=1", flush=True)
            return latch.pending()

        runner = BoundedSupervisorServiceRunner(
            contract=contract,
            workers=workers,
            max_cycles=args.max_cycles,
            interval_seconds=args.interval,
            now_provider=utc_now,
            sleep_fn=time.sleep,
            signal_provider=signal_provider,
            terminate_timeout_seconds=2,
        )

        with InstalledSupervisorSignalHandlers(latch):
            report = runner.run()

        print(
            f"FINAL_STATE={report.final_snapshot.state.value}",
            flush=True,
        )
        print(
            "STOP_REASON="
            f"{report.final_snapshot.stop_reason.value if report.final_snapshot.stop_reason else 'none'}",
            flush=True,
        )
        print(
            "WORKERS_STOPPED="
            + str(
                all(
                    not observation.running
                    for observation in report.final_observations
                )
            ).lower(),
            flush=True,
        )


if __name__ == "__main__":
    main()
