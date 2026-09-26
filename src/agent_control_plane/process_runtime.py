"""Bounded caller-driven subprocess control for ACP relay workers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Mapping, Optional, Sequence

from .authority import AuthorityValidationError
from .process_supervision import (
    ProcessFailureState,
    ProcessSupervisionDecision,
    ProcessSupervisionPolicy,
)


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    return value.strip()


@dataclass(frozen=True)
class ManagedProcessSpec:
    process_id: str
    argv: tuple[str, ...]
    cwd: Optional[str] = None
    env: Optional[Mapping[str, str]] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "process_id",
            _required(self.process_id, "process_id"),
        )
        if (
            not isinstance(self.argv, tuple)
            or not self.argv
            or not all(
                isinstance(arg, str) and arg != ""
                for arg in self.argv
            )
        ):
            raise AuthorityValidationError(
                "argv must be a non-empty tuple of strings"
            )
        if self.cwd is not None:
            _required(self.cwd, "cwd")
        if self.env is not None:
            if not isinstance(self.env, Mapping):
                raise AuthorityValidationError("env must be a mapping")
            for key, value in self.env.items():
                _required(key, "env key")
                if not isinstance(value, str):
                    raise AuthorityValidationError(
                        "env values must be strings"
                    )


@dataclass(frozen=True)
class ProcessObservation:
    process_id: str
    running: bool
    returncode: Optional[int]
    pid: Optional[int]


class ManagedProcessController:
    """Explicit process start/observe/terminate/restart controller."""

    def __init__(self, spec: ManagedProcessSpec) -> None:
        if not isinstance(spec, ManagedProcessSpec):
            raise AuthorityValidationError(
                "spec must be ManagedProcessSpec"
            )
        self.spec = spec
        self._process: Optional[subprocess.Popen] = None

    def start(self) -> ProcessObservation:
        if self._process is not None and self._process.poll() is None:
            raise AuthorityValidationError("managed process already running")

        cwd = None if self.spec.cwd is None else str(Path(self.spec.cwd))
        env = None if self.spec.env is None else dict(self.spec.env)
        self._process = subprocess.Popen(
            list(self.spec.argv),
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return self.observe()

    def observe(self) -> ProcessObservation:
        if self._process is None:
            return ProcessObservation(
                process_id=self.spec.process_id,
                running=False,
                returncode=None,
                pid=None,
            )
        returncode = self._process.poll()
        return ProcessObservation(
            process_id=self.spec.process_id,
            running=returncode is None,
            returncode=returncode,
            pid=self._process.pid,
        )

    def terminate(self, *, timeout_seconds: float = 5.0) -> ProcessObservation:
        if timeout_seconds <= 0:
            raise AuthorityValidationError(
                "timeout_seconds must be > 0"
            )
        if self._process is None:
            return self.observe()
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=timeout_seconds)
        return self.observe()

    def restart(self, *, timeout_seconds: float = 5.0) -> ProcessObservation:
        if self._process is not None and self._process.poll() is None:
            self.terminate(timeout_seconds=timeout_seconds)
        return self.start()

    def read_output(self) -> str:
        if self._process is None or self._process.stdout is None:
            return ""
        return self._process.stdout.read()


@dataclass(frozen=True)
class ProcessSupervisionExecution:
    decision: ProcessSupervisionDecision
    observation: ProcessObservation


class SupervisedProcessController:
    """Apply a deterministic supervision decision to one managed process."""

    def __init__(
        self,
        *,
        controller: ManagedProcessController,
        policy: ProcessSupervisionPolicy,
    ) -> None:
        if not isinstance(controller, ManagedProcessController):
            raise AuthorityValidationError(
                "controller must be ManagedProcessController"
            )
        if not isinstance(policy, ProcessSupervisionPolicy):
            raise AuthorityValidationError(
                "policy must be ProcessSupervisionPolicy"
            )
        self.controller = controller
        self.policy = policy

    def handle_failure(
        self,
        state: ProcessFailureState,
        *,
        now: str,
        timeout_seconds: float = 5.0,
    ) -> ProcessSupervisionExecution:
        decision = self.policy.decide(state, now=now)
        if decision is ProcessSupervisionDecision.RESTART:
            observation = self.controller.restart(
                timeout_seconds=timeout_seconds
            )
        elif decision is ProcessSupervisionDecision.HOLD:
            observation = self.controller.observe()
        else:
            observation = self.controller.terminate(
                timeout_seconds=timeout_seconds
            )
        return ProcessSupervisionExecution(
            decision=decision,
            observation=observation,
        )
