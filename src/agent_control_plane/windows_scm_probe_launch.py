"""Deterministic launch specification for the disposable SCM identity probe."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib, json
from pathlib import Path
from .authority import AuthorityValidationError

@dataclass(frozen=True)
class DisposableProbeLaunchSpec:
    python_executable: str
    source_root: str
    lab_root: str
    module: str="agent_control_plane.windows_scm_identity_probe"
    def __post_init__(self):
        py=Path(self.python_executable).resolve(); src=Path(self.source_root).resolve(); lab=Path(self.lab_root).resolve()
        if not py.is_file(): raise AuthorityValidationError("probe Python executable missing")
        if not (src/"agent_control_plane"/"windows_scm_identity_probe.py").is_file(): raise AuthorityValidationError("probe source root missing module")
        parts=tuple(x.casefold() for x in lab.parts)
        if "staging" not in parts or "acp-executor-isolation-lab" not in parts: raise AuthorityValidationError("lab_root outside disposable isolation lab")
        object.__setattr__(self,"python_executable",str(py));object.__setattr__(self,"source_root",str(src));object.__setattr__(self,"lab_root",str(lab))
    def argv(self)->tuple[str,...]:
        return (self.python_executable,"-I","-c",
          "import sys;sys.path.insert(0,sys.argv[1]);from agent_control_plane.windows_scm_identity_probe import main;raise SystemExit(main(sys.argv[2:]))",
          self.source_root,"--root",self.lab_root,"--hold-seconds","0")
    def content_sha256(self)->str:
        return hashlib.sha256(json.dumps(self.argv(),separators=(",",":")).encode()).hexdigest()
