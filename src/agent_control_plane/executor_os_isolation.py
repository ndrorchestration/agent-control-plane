"""Fail-closed model for Windows service token/isolation evidence."""
from dataclasses import dataclass

@dataclass(frozen=True)
class ServiceIsolationEvidence:
    dedicated_account: bool
    non_admin_account: bool
    restricted_service_sid: bool
    explicit_required_privileges: bool
    real_project_acl_absent: bool
    binary_acl_isolated: bool
    live_token_observed: bool = False

    @property
    def containment_controls_established(self) -> bool:
        return all((self.dedicated_account,self.non_admin_account,self.restricted_service_sid,self.real_project_acl_absent,self.binary_acl_isolated))

    @property
    def minimal_token_verified(self) -> bool:
        return self.containment_controls_established and self.explicit_required_privileges and self.live_token_observed

    @property
    def complete_os_isolation_verified(self) -> bool:
        return False
