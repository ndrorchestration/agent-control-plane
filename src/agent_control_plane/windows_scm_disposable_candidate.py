"""Build the exact non-mutating registration candidate for the disposable lab."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib, sys
from pathlib import Path
from .windows_scm_registration import WindowsScmServiceRegistrationManifest,WindowsScmServiceRegistrationPolicy,WindowsScmServiceStartType
from .windows_scm_registration_plan import WindowsScmServiceRegistrationPlanner
from .windows_scm_binary_verification import WindowsScmServiceRegistrationAdmission

SERVICE_NAME="ACPExecutorLabProbe"
ACCOUNT_NAME=r".\ACPExecutorLab"
CREDENTIAL_REFERENCE="operator-transient:ACPExecutorLab"

@dataclass(frozen=True)
class DisposableScmCandidate:
 manifest: WindowsScmServiceRegistrationManifest
 policy: WindowsScmServiceRegistrationPolicy
 plan: object

def build_candidate(*, python_executable: str|None=None)->DisposableScmCandidate:
 exe=Path(python_executable or sys.executable).resolve()
 digest=hashlib.sha256(exe.read_bytes()).hexdigest()
 manifest=WindowsScmServiceRegistrationManifest(
   service_name=SERVICE_NAME,
   display_name="ACP Disposable Executor Identity Probe",
   binary_path=str(exe),
   account_name=ACCOUNT_NAME,
   start_type=WindowsScmServiceStartType.DEMAND_START,
   description="Disposable ACP #118 service identity probe; no project execution authority.",
   dependencies=(),
   delayed_auto_start=False,
   credential_reference=CREDENTIAL_REFERENCE,
   binary_sha256=digest,
 )
 policy=WindowsScmServiceRegistrationPolicy(
   allowed_binary_paths=(manifest.binary_path,),
   allowed_accounts=(manifest.account_name,),
   allowed_start_types=(WindowsScmServiceStartType.DEMAND_START,),
   allowed_manifest_sha256=(manifest.content_sha256(),),
   allow_local_system=False,
   allow_delayed_auto_start=False,
   require_binary_sha256=True,
 )
 admission=WindowsScmServiceRegistrationAdmission(policy=policy).assert_admitted(manifest)
 plan=WindowsScmServiceRegistrationPlanner(policy=policy).compile(manifest)
 assert admission.binary.actual_sha256==digest
 return DisposableScmCandidate(manifest,policy,plan)
