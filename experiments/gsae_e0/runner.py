"""Source binding and deterministic native ACP observations for GSAE-E0 Stage A."""

from pathlib import Path
import re
import subprocess
from typing import Callable

from agent_control_plane import ControlPlane, ExecutionBudget, Task, TaskState
from agent_control_plane.contract import (
    SCHEMA_VERSION,
    ArtifactRef,
    ComponentIdentity,
    ContractValidationError,
    ExecutionEvent,
    ExecutionIdentity,
    TraceContext,
    map_provenance_event,
)
from agent_control_plane.provenance import ProvenanceEvent

from .classify import (
    aggregate_disposition,
    classify_authority_fixture,
    execution_v1_surface_paths,
)
from .fixtures import fixture_manifest_sha256, load_fixture_manifest
from .manifest import EvidenceBundle, build_evidence_bundle, result_id
from .schema import (
    ExceptionClass,
    FixtureDisposition,
    FixtureFamily,
    FixtureResult,
    FixtureValidationError,
)


class SourceBindingError(RuntimeError):
    """Raised when the working tree cannot prove the frozen ACP source binding."""


class ExecutionGuardError(RuntimeError):
    """Raised when Stage-A orchestration lacks a required execution guard or binding."""


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def verify_source_binding(repo_root: Path, expected_sha: str) -> None:
    """Prove the frozen source commit exists and the ACP package is content-equivalent."""
    if re.fullmatch(r"[0-9a-f]{40}", expected_sha) is None:
        raise SourceBindingError("expected_sha must be 40 lowercase hexadecimal characters")

    source = _git(repo_root, "cat-file", "-e", f"{expected_sha}^{commit}")
    if source.returncode != 0:
        detail = source.stderr.strip() or source.stdout.strip() or "source commit not found"
        raise SourceBindingError(f"source-under-test commit not established: {detail}")

    diff = _git(repo_root, "diff", "--quiet", expected_sha, "HEAD", "--", "src/agent_control_plane")
    if diff.returncode != 0:
        detail = diff.stderr.strip() or diff.stdout.strip() or "ACP source differs"
        raise SourceBindingError(f"ACP source package drifted from source under test: {detail}")


def _event_kwargs() -> dict[str, object]:
    return {
        "event_type": "task.completed",
        "identity": ExecutionIdentity(execution_id="exec-1", run_id="run-1"),
        "trace": TraceContext(trace_id="trace-1", span_id="span-1"),
        "component": ComponentIdentity(
            component_id="kernel",
            component_type="kernel",
            runtime_id="python",
            adapter_id="native-acp",
        ),
        "task_id": "task-1",
        "status": "completed",
        "utc_timestamp": "2026-09-16T00:00:00Z",
        "monotonic_ns": 42,
    }


def _native_01() -> tuple[FixtureDisposition, str]:
    plane = ControlPlane(run_id="gsae-e0-native-01")
    plane.register("echo", lambda task: task.payload)
    task = plane.dispatch("echo", Task(payload="hello", id="task-native-01"))
    if task.state is not TaskState.COMPLETED:
        return FixtureDisposition.NOT_ESTABLISHED, f"unexpected state={task.state.value}"
    if not any(event.event == "task.completed" for event in plane.events):
        return FixtureDisposition.NOT_ESTABLISHED, "missing task.completed evidence"
    return FixtureDisposition.PASS, "task.completed recorded"


def _native_02() -> tuple[FixtureDisposition, str]:
    plane = ControlPlane(policy=lambda capability, task: "blocked", run_id="gsae-e0-native-02")
    plane.register("echo", lambda task: task.payload)
    task = plane.dispatch("echo", Task(payload="hello", id="task-native-02"))
    if task.error != "blocked":
        return FixtureDisposition.NOT_ESTABLISHED, "policy denial reason not retained"
    if not any(event.event == "task.denied" for event in plane.events):
        return FixtureDisposition.NOT_ESTABLISHED, "missing task.denied evidence"
    return FixtureDisposition.PASS, "task.denied recorded"


def _native_03() -> tuple[FixtureDisposition, str]:
    plane = ControlPlane(run_id="gsae-e0-native-03")
    task = Task(payload="hello", id="task-native-03")
    try:
        plane.dispatch("missing", task)
    except KeyError:
        if any(event.event == "task.rejected" for event in plane.events):
            return FixtureDisposition.PASS, "task.rejected recorded before KeyError"
        return FixtureDisposition.NOT_ESTABLISHED, "KeyError without task.rejected evidence"
    return FixtureDisposition.NOT_ESTABLISHED, "unknown capability did not raise KeyError"


def _native_04() -> tuple[FixtureDisposition, str]:
    def fail(task: Task) -> object:
        raise RuntimeError("synthetic failure")

    plane = ControlPlane(run_id="gsae-e0-native-04")
    plane.register("fail", fail)
    task = plane.dispatch("fail", Task(payload=None, id="task-native-04"))
    if task.state is not TaskState.FAILED:
        return FixtureDisposition.NOT_ESTABLISHED, f"unexpected state={task.state.value}"
    if not any(event.event == "task.failed" for event in plane.events):
        return FixtureDisposition.NOT_ESTABLISHED, "missing task.failed evidence"
    return FixtureDisposition.PASS, "task.failed recorded"


def _native_05() -> tuple[FixtureDisposition, str]:
    plane = ControlPlane(run_id="gsae-e0-native-05")
    task = plane.cancel(Task(payload=None, id="task-native-05"))
    if task.state is not TaskState.CANCELLED:
        return FixtureDisposition.NOT_ESTABLISHED, f"unexpected state={task.state.value}"
    if not any(event.event == "task.cancelled" for event in plane.events):
        return FixtureDisposition.NOT_ESTABLISHED, "missing task.cancelled evidence"
    return FixtureDisposition.PASS, "task.cancelled recorded"


def _native_06() -> tuple[FixtureDisposition, str]:
    def consume(task: Task) -> object:
        task.consume(steps=1)
        return "unreachable"

    plane = ControlPlane(run_id="gsae-e0-native-06")
    plane.register("consume", consume)
    task = plane.dispatch(
        "consume",
        Task(
            payload=None,
            id="task-native-06",
            budget=ExecutionBudget(max_steps=0),
        ),
    )
    if task.state is not TaskState.BUDGET_EXHAUSTED:
        return FixtureDisposition.NOT_ESTABLISHED, f"unexpected state={task.state.value}"
    if not any(event.event == "task.budget_exhausted" for event in plane.events):
        return FixtureDisposition.NOT_ESTABLISHED, "missing task.budget_exhausted evidence"
    return FixtureDisposition.PASS, "task.budget_exhausted recorded"


def _native_07() -> tuple[FixtureDisposition, str]:
    event = ExecutionEvent(
        **_event_kwargs(),
        input_artifacts=(ArtifactRef(artifact_id="input-1", kind="input"),),
        output_artifacts=(ArtifactRef(artifact_id="output-1", kind="output"),),
    )
    if event.input_artifacts[0].artifact_id != "input-1" or event.output_artifacts[0].artifact_id != "output-1":
        return FixtureDisposition.NOT_ESTABLISHED, "artifact identities not preserved"
    return FixtureDisposition.PASS, "input/output artifact linkage preserved"


def _native_08() -> tuple[FixtureDisposition, str]:
    trace = TraceContext(trace_id="trace-1", span_id="span-1", parent_span_id="span-0")
    if trace.parent_span_id != "span-0":
        return FixtureDisposition.NOT_ESTABLISHED, "parent span not preserved"
    return FixtureDisposition.PASS, "parent_span_id structurally preserved"


def _native_09() -> tuple[FixtureDisposition, str]:
    event = ExecutionEvent(**_event_kwargs(), policy_decision_ref="decision-1")
    if event.policy_decision_ref != "decision-1":
        return FixtureDisposition.NOT_ESTABLISHED, "policy decision reference not preserved"
    return FixtureDisposition.PASS, "policy_decision_ref structurally preserved"


def _native_10() -> tuple[FixtureDisposition, str]:
    source = ProvenanceEvent(
        event="task.completed",
        task_id="task-1",
        run_id="run-1",
        capability="echo",
        state="completed",
        timestamp="2026-09-16T00:00:00Z",
    )
    mapped = map_provenance_event(
        source,
        identity=ExecutionIdentity(execution_id="exec-1", run_id="run-1"),
        trace=TraceContext(trace_id="trace-1", span_id="span-1"),
        component=ComponentIdentity(
            component_id="kernel",
            component_type="kernel",
            runtime_id="python",
            adapter_id="native-acp",
        ),
        monotonic_ns=1,
    )
    if (
        mapped.event_type != source.event
        or mapped.task_id != source.task_id
        or mapped.capability != source.capability
        or mapped.status != source.state
    ):
        return FixtureDisposition.NOT_ESTABLISHED, "mapped provenance fields differ"
    return FixtureDisposition.PASS, "mapped provenance preserves event/task/capability/state"


def _expected_rejection(action: Callable[[], object], fragment: str) -> tuple[FixtureDisposition, str]:
    try:
        action()
    except ContractValidationError as exc:
        message = str(exc)
        if fragment in message:
            return FixtureDisposition.EXPECTED_REJECTION, message
        return FixtureDisposition.NOT_ESTABLISHED, f"unexpected validation message: {message}"
    return FixtureDisposition.NOT_ESTABLISHED, "expected ContractValidationError was not raised"


def _neg_01() -> tuple[FixtureDisposition, str]:
    source = ProvenanceEvent(
        event="task.started",
        task_id="task-1",
        run_id="run-source",
        state="running",
        timestamp="2026-09-16T00:00:00Z",
    )
    return _expected_rejection(
        lambda: map_provenance_event(
            source,
            identity=ExecutionIdentity(execution_id="exec-1", run_id="run-contract"),
            trace=TraceContext(trace_id="trace-1", span_id="span-1"),
            component=ComponentIdentity(
                component_id="kernel",
                component_type="kernel",
                runtime_id="python",
                adapter_id="native-acp",
            ),
            monotonic_ns=1,
        ),
        "run_id",
    )


def _neg_02() -> tuple[FixtureDisposition, str]:
    return _expected_rejection(
        lambda: ExecutionIdentity(
            execution_id="exec-1",
            run_id="run-1",
            schema_version=f"{SCHEMA_VERSION}.unsupported",
        ),
        "schema_version",
    )


def _neg_03() -> tuple[FixtureDisposition, str]:
    return _expected_rejection(
        lambda: ExecutionIdentity(execution_id=" ", run_id="run-1"),
        "execution_id",
    )


def _neg_04() -> tuple[FixtureDisposition, str]:
    return _expected_rejection(
        lambda: TraceContext(trace_id="trace-1", span_id="span-1", parent_span_id="span-1"),
        "parent_span_id",
    )


def _neg_05() -> tuple[FixtureDisposition, str]:
    return _expected_rejection(
        lambda: ArtifactRef(artifact_id="artifact-1", kind="input", sha256="not-a-hash"),
        "sha256",
    )


def _neg_06() -> tuple[FixtureDisposition, str]:
    for value in (-1, "1"):
        disposition, summary = _expected_rejection(
            lambda value=value: ExecutionEvent(**{**_event_kwargs(), "monotonic_ns": value}),
            "monotonic_ns",
        )
        if disposition is not FixtureDisposition.EXPECTED_REJECTION:
            return disposition, summary
    return FixtureDisposition.EXPECTED_REJECTION, "monotonic_ns rejects negative and non-integer values"


def _neg_07() -> tuple[FixtureDisposition, str]:
    for value in ("2026-09-16T00:00:00", "2026-09-16T01:00:00+01:00"):
        disposition, summary = _expected_rejection(
            lambda value=value: ExecutionEvent(**{**_event_kwargs(), "utc_timestamp": value}),
            "utc_timestamp",
        )
        if disposition is not FixtureDisposition.EXPECTED_REJECTION:
            return disposition, summary
    return FixtureDisposition.EXPECTED_REJECTION, "utc_timestamp rejects naive and non-UTC values"


def _neg_08() -> tuple[FixtureDisposition, str]:
    return _expected_rejection(
        lambda: ExecutionEvent(**{**_event_kwargs(), "component": "not-a-component"}),
        "component",
    )


_OBSERVATIONS: dict[str, Callable[[], tuple[FixtureDisposition, str]]] = {
    "NATIVE-01": _native_01,
    "NATIVE-02": _native_02,
    "NATIVE-03": _native_03,
    "NATIVE-04": _native_04,
    "NATIVE-05": _native_05,
    "NATIVE-06": _native_06,
    "NATIVE-07": _native_07,
    "NATIVE-08": _native_08,
    "NATIVE-09": _native_09,
    "NATIVE-10": _native_10,
    "NEG-01": _neg_01,
    "NEG-02": _neg_02,
    "NEG-03": _neg_03,
    "NEG-04": _neg_04,
    "NEG-05": _neg_05,
    "NEG-06": _neg_06,
    "NEG-07": _neg_07,
    "NEG-08": _neg_08,
}


def observe_native_fixture(fixture_id: str) -> tuple[FixtureDisposition, str]:
    """Observe one already-established ACP native/negative behavior deterministically."""
    observation = _OBSERVATIONS.get(fixture_id)
    if observation is None:
        raise ValueError(f"unknown native fixture: {fixture_id}")
    return observation()


def _guard_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExecutionGuardError(f"{field_name} must be a non-blank string")
    return value.strip()


def _native_result(
    *,
    fixture_id: str,
    disposition: FixtureDisposition,
    summary: str,
    run_id: str,
    source_under_test_sha: str,
    schema_version: str,
    fixture_manifest_sha256: str,
) -> FixtureResult:
    exception_class = None
    if disposition is FixtureDisposition.NOT_ESTABLISHED:
        exception_class = ExceptionClass.IMPLEMENTATION_DEFECT
    return FixtureResult(
        result_id=result_id(run_id, fixture_id, 1),
        run_id=run_id,
        attempt=1,
        fixture_id=fixture_id,
        disposition=disposition,
        source_under_test_sha=source_under_test_sha,
        schema_version=schema_version,
        fixture_manifest_sha256=fixture_manifest_sha256,
        exception_class=exception_class,
        evidence_summary=summary,
    )


def run_stage_a(
    *,
    repo_root: Path,
    fixture_path: Path,
    protocol_version: str,
    authorization_record_id: str,
    run_id: str,
    harness_commit_sha: str,
    test_command: str,
    test_summary: str,
) -> EvidenceBundle:
    """Run one explicitly identified Stage-A fixture manifest in memory only.

    This function requires an explicit authorization-record identifier but does
    not itself decide whether that external governance record is valid. The GSAE
    control record remains the authority for execution authorization.
    """
    protocol = _guard_text(protocol_version, "protocol_version")
    authorization = _guard_text(authorization_record_id, "authorization_record_id")
    run = _guard_text(run_id, "run_id")
    harness_sha = _guard_text(harness_commit_sha, "harness_commit_sha")
    command = _guard_text(test_command, "test_command")
    summary = _guard_text(test_summary, "test_summary")
    if re.fullmatch(r"[0-9a-f]{40}", harness_sha) is None:
        raise ExecutionGuardError(
            "harness_commit_sha must be 40 lowercase hexadecimal characters"
        )

    try:
        manifest = load_fixture_manifest(fixture_path)
    except (OSError, ValueError, FixtureValidationError) as exc:
        raise ExecutionGuardError(f"fixture manifest not established: {exc}") from exc

    if manifest.experiment_id != "GSAE-E0":
        raise ExecutionGuardError(
            f"experiment_id must be GSAE-E0, got {manifest.experiment_id!r}"
        )
    if manifest.schema_version != SCHEMA_VERSION:
        raise ExecutionGuardError(
            f"schema_version must be {SCHEMA_VERSION}, got {manifest.schema_version!r}"
        )

    try:
        verify_source_binding(repo_root, manifest.source_under_test_sha)
    except SourceBindingError as exc:
        raise ExecutionGuardError(f"source binding not established: {exc}") from exc

    try:
        fixture_hash = fixture_manifest_sha256(fixture_path)
    except (OSError, ValueError, FixtureValidationError) as exc:
        raise ExecutionGuardError(f"fixture manifest identity not established: {exc}") from exc

    surface = execution_v1_surface_paths()
    results: list[FixtureResult] = []

    for fixture in manifest.fixtures:
        if fixture.family in {FixtureFamily.NATIVE, FixtureFamily.NEGATIVE}:
            try:
                disposition, evidence_summary = observe_native_fixture(fixture.fixture_id)
            except Exception as exc:  # apparatus must convert unexpected observation errors to evidence
                disposition = FixtureDisposition.NOT_ESTABLISHED
                evidence_summary = f"unexpected observation error: {type(exc).__name__}: {exc}"
            results.append(
                _native_result(
                    fixture_id=fixture.fixture_id,
                    disposition=disposition,
                    summary=evidence_summary,
                    run_id=run,
                    source_under_test_sha=manifest.source_under_test_sha,
                    schema_version=manifest.schema_version,
                    fixture_manifest_sha256=fixture_hash,
                )
            )
        elif fixture.family is FixtureFamily.AUTHORITY:
            results.append(
                classify_authority_fixture(
                    fixture,
                    surface,
                    result_id=result_id(run, fixture.fixture_id, 1),
                    run_id=run,
                    attempt=1,
                    source_under_test_sha=manifest.source_under_test_sha,
                    schema_version=manifest.schema_version,
                    fixture_manifest_sha256=fixture_hash,
                )
            )
        else:
            raise ExecutionGuardError(f"unsupported fixture family: {fixture.family.value}")

    fixture_ids = [fixture.fixture_id for fixture in manifest.fixtures]
    result_fixture_ids = [result.fixture_id for result in results]
    if len(results) != len(manifest.fixtures) or set(result_fixture_ids) != set(fixture_ids):
        raise ExecutionGuardError("exactly one result per frozen fixture was not established")

    aggregate = aggregate_disposition(manifest.fixtures, results)
    return build_evidence_bundle(
        experiment_id=manifest.experiment_id,
        protocol_version=protocol,
        run_id=run,
        authorization_record_id=authorization,
        source_under_test_sha=manifest.source_under_test_sha,
        harness_commit_sha=harness_sha,
        schema_version=manifest.schema_version,
        fixture_set_version=manifest.fixture_set_version,
        fixture_manifest_sha256=fixture_hash,
        results=results,
        aggregate_disposition=aggregate,
        test_command=command,
        test_summary=summary,
        evidence_ceiling=(
            "GSAE-E0 Stage-A contract-feasibility evidence only; not portability, "
            "authorization, governance efficacy, safety, security, or production readiness."
        ),
        known_fixture_ids=set(fixture_ids),
    )
