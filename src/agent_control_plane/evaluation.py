"""Small deterministic evaluation harness for ACP kernel behavior."""

from dataclasses import dataclass
from typing import Callable, List

from .core import ControlPlane, Task, TaskState


@dataclass(frozen=True)
class EvaluationCase:
    name: str
    run: Callable[[ControlPlane], bool]


@dataclass(frozen=True)
class EvaluationResult:
    name: str
    passed: bool


def run_evaluation(cases: List[EvaluationCase]) -> List[EvaluationResult]:
    results = []
    for case in cases:
        plane = ControlPlane()
        results.append(EvaluationResult(name=case.name, passed=bool(case.run(plane))))
    return results


def smoke_cases() -> List[EvaluationCase]:
    def successful_dispatch(plane: ControlPlane) -> bool:
        plane.register("echo", lambda task: task.payload)
        result = plane.dispatch("echo", Task(payload="ok"))
        return result.state is TaskState.COMPLETED and result.result == "ok"

    def unknown_capability(plane: ControlPlane) -> bool:
        try:
            plane.dispatch("missing", Task(payload=None))
        except KeyError:
            return True
        return False

    return [
        EvaluationCase("successful_dispatch", successful_dispatch),
        EvaluationCase("unknown_capability", unknown_capability),
    ]
