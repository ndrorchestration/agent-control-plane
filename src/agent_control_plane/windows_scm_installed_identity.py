"""Read-only verification of an installed Windows SCM service identity."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Mapping
from .authority import AuthorityValidationError

@dataclass(frozen=True)
class WindowsInstalledServiceIdentity:
    service_name: str
    account_name: str
    binary_path: str
    binary_sha256: str
    start_mode: str
    state: str

@dataclass(frozen=True)
class WindowsInstalledServiceIdentityAssessment:
    matched: bool
    reasons: tuple[str, ...]

def sha256_path(path: str) -> str:
    p=Path(path)
    if not p.is_file():
        raise AuthorityValidationError("installed service binary does not exist")
    h=hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def assess_installed_service_identity(
    observed: WindowsInstalledServiceIdentity,
    *,
    expected_service_name: str,
    expected_account_name: str,
    expected_binary_path: str,
    expected_binary_sha256: str,
    allowed_start_modes: tuple[str, ...] = ("Manual", "Disabled"),
) -> WindowsInstalledServiceIdentityAssessment:
    reasons=[]
    if observed.service_name.casefold()!=expected_service_name.casefold():
        reasons.append("service name mismatch")
    if observed.account_name.casefold()!=expected_account_name.casefold():
        reasons.append("service account mismatch")
    if str(Path(observed.binary_path)).casefold()!=str(Path(expected_binary_path)).casefold():
        reasons.append("service binary path mismatch")
    if observed.binary_sha256.lower()!=expected_binary_sha256.lower():
        reasons.append("service binary hash mismatch")
    if observed.start_mode not in allowed_start_modes:
        reasons.append("service start mode outside bounded lab policy")
    return WindowsInstalledServiceIdentityAssessment(not reasons, tuple(reasons))

def identity_from_cim_record(record: Mapping[str, object], *, binary_sha256: str) -> WindowsInstalledServiceIdentity:
    required=("Name","StartName","PathName","StartMode","State")
    if any(key not in record or record[key] is None for key in required):
        raise AuthorityValidationError("CIM service record missing required identity field")
    raw_path=str(record["PathName"]).strip()
    if raw_path.startswith('"'):
        end=raw_path.find('"',1)
        if end<1: raise AuthorityValidationError("unterminated quoted service binary path")
        binary_path=raw_path[1:end]
    else:
        binary_path=raw_path.split(" ",1)[0]
    return WindowsInstalledServiceIdentity(
        service_name=str(record["Name"]),
        account_name=str(record["StartName"]),
        binary_path=binary_path,
        binary_sha256=binary_sha256.lower(),
        start_mode=str(record["StartMode"]),
        state=str(record["State"]),
    )
