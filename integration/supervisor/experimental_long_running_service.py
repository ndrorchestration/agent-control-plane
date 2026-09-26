"""Experimental long-running ACP supervisor used only for integration evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import argparse
import os
from pathlib import Path
import sys
import tempfile
import time

from agent_control_plane.process_execution_admission import (
    AdmittedManagedProcessController,
    ProcessExecutionAdmissionPolicy,
    managed_process_spec_sha256,
)
from agent_control_plane.process_monitor import (
    DurableProcessFailureStore,
    ProcessMonitorTick,
)
from agent_control_plane.process_monitor_cadence import (
    DurableProcessMonitorCadenceStore,
    ProcessMonitorCadencePolicy,
    ScheduledProcessMonitor,
)
from agent_control_plane.process_runtime import ManagedProcessSpec
from agent_control_plane.process_supervision import ProcessSupervisionPolicy
from agent_control_plane.supervisor_ownership import (
    SupervisorOwnershipLeaseStore,
)
from agent_control_plane.supervisor_runtime_checkpoint import (
    DurableSupervisorRuntimeCheckpointStore,
)
from agent_control_plane.supervisor_service import (
    SupervisorServiceContract,
    SupervisorWorkerRegistration,
)
from agent_control_plane.supervisor_service_runner import (
    ExperimentalLongRunningSupervisorServiceRunner,
    SupervisorLeaseConfiguration,
    SupervisorRuntimeCheckpointConfiguration,
    SupervisorWorkerRuntime,
)
from agent_control_plane.supervisor_signal import SupervisorSignalLatch


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=float, default=0.05)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="acp-long-running-") as tmp:
        root = Path(tmp)
        registration = SupervisorWorkerRegistration(
            worker_id="relay-a",
            process_id="relay-a-process",
            ownership_token="relay-a-owner",
        )
        spec = ManagedProcessSpec(
            process_id=registration.process_id,
            argv=(
                sys.executable,
                "-c",
                "import time; time.sleep(120)",
            ),
            cwd=str(root),
            env={"ACP_SERVICE_TEST": "1"},
        )
        policy = ProcessExecutionAdmissionPolicy(
            allowed_executables=(sys.executable,),
            allowed_cwd_roots=(str(root),),
            allowed_environment_keys=("ACP_SERVICE_TEST",),
            allowed_spec_sha256=(managed_process_spec_sha256(spec),),
            required_effective_uid=(
                os.geteuid() if hasattr(os, "geteuid") else None
            ),
        )
        controller = AdmittedManagedProcessController(
            spec,
            admission_policy=policy,
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
            service_id="experimental-long-running",
            workers=(registration,),
        )

        lease_store = SupervisorOwnershipLeaseStore(
            root / "ownership.sqlite3"
        )
        checkpoint_store = DurableSupervisorRuntimeCheckpointStore(
            root / "runtime.sqlite3"
        )

        with SupervisorSignalLatch() as latch:
            announced = False

            def signal_provider(index: int):
                nonlocal announced
                if not announced:
                    announced = True
                    print("LONG_RUNNING_READY=1", flush=True)
                return latch.signal_name()

            runner = ExperimentalLongRunningSupervisorServiceRunner(
                contract=contract,
                workers=(runtime,),
                interval_seconds=args.interval,
                now_provider=utc_now,
                sleep_fn=time.sleep,
                signal_provider=signal_provider,
                terminate_timeout_seconds=2,
                lease_configuration=SupervisorLeaseConfiguration(
                    store=lease_store,
                    owner_id="experimental-long-running",
                    instance_token="integration-instance",
                    ttl_seconds=30,
                ),
                runtime_checkpoint_configuration=(
                    SupervisorRuntimeCheckpointConfiguration(
                        store=checkpoint_store,
                    )
                ),
            )
            report = runner.run()

        checkpoint = checkpoint_store.get("experimental-long-running")
        service_lease = lease_store.get(
            "service:experimental-long-running"
        )
        print(
            f"LONG_RUNNING_FINAL_STATE={report.final_snapshot.state.value}",
            flush=True,
        )
        print(
            "LONG_RUNNING_STOP_REASON="
            f"{report.final_snapshot.stop_reason.value}",
            flush=True,
        )
        print(
            "LONG_RUNNING_CHILD_RUNNING="
            f"{int(report.final_observations[0].running)}",
            flush=True,
        )
        print(
            "LONG_RUNNING_CHECKPOINT_STATE="
            f"{checkpoint.state.value if checkpoint else 'missing'}",
            flush=True,
        )
        print(
            "LONG_RUNNING_RUNTIME_GENERATION="
            f"{report.runtime_generation}",
            flush=True,
        )
        print(
            "LONG_RUNNING_SERVICE_LEASE_RELEASED="
            f"{int(service_lease is not None and service_lease.released_at is not None)}",
            flush=True,
        )


if __name__ == "__main__":
    main()
