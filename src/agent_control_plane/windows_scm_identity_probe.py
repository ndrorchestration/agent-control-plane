"""Disposable SCM identity probe. No executor or repository mutation capability."""
from __future__ import annotations
import argparse
import time
from pathlib import Path
from .authority import AuthorityValidationError

PROBE_ID="acp-disposable-scm-identity-probe.v1"

def validate_probe_root(root: str) -> Path:
    p=Path(root).resolve()
    parts=tuple(x.casefold() for x in p.parts)
    if "staging" not in parts or "acp-executor-isolation-lab" not in parts:
        raise AuthorityValidationError("probe root must be the disposable ACP isolation lab")
    return p

def run_probe(*, root: str, hold_seconds: float=0.0) -> int:
    validate_probe_root(root)
    if hold_seconds < 0 or hold_seconds > 30:
        raise AuthorityValidationError("hold_seconds must be between 0 and 30")
    if hold_seconds:
        time.sleep(hold_seconds)
    return 0

def main(argv=None) -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",required=True)
    parser.add_argument("--hold-seconds",type=float,default=0.0)
    args=parser.parse_args(argv)
    return run_probe(root=args.root,hold_seconds=args.hold_seconds)

if __name__=="__main__":
    raise SystemExit(main())
