import hashlib
import os

import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.windows_scm_binary_verification import (
    WindowsScmBinaryVerifier,
    WindowsScmServiceRegistrationAdmission,
)
from agent_control_plane.windows_scm_registration import (
    WindowsScmServiceRegistrationManifest,
    WindowsScmServiceRegistrationPolicy,
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def manifest_for(path, digest):
    return WindowsScmServiceRegistrationManifest(
        service_name="ACPAgentControlPlane",
        display_name="ACP Agent Control Plane",
        binary_path=str(path),
        account_name=r"NT SERVICE\ACPAgentControlPlane",
        binary_sha256=digest,
    )


def policy_for(manifest):
    return WindowsScmServiceRegistrationPolicy(
        allowed_binary_paths=(manifest.binary_path,),
        allowed_accounts=(manifest.account_name,),
        allowed_manifest_sha256=(manifest.content_sha256(),),
    )


def test_verifier_configuration_validation():
    with pytest.raises(AuthorityValidationError):
        WindowsScmBinaryVerifier(chunk_size=0)


@pytest.mark.skipif(os.name != "nt", reason="Windows-only on-disk verification")
def test_exact_binary_hash_is_verified(tmp_path):
    binary = tmp_path / "acp-supervisor.exe"
    payload = b"ACP test binary payload"
    binary.write_bytes(payload)
    manifest = manifest_for(binary, sha256_bytes(payload))

    result = WindowsScmBinaryVerifier(chunk_size=4).verify(manifest)

    assert result.matched is True
    assert result.actual_sha256 == sha256_bytes(payload)
    assert result.expected_sha256 == sha256_bytes(payload)
    assert result.size_bytes == len(payload)


@pytest.mark.skipif(os.name != "nt", reason="Windows-only on-disk verification")
def test_binary_hash_mismatch_fails_closed(tmp_path):
    binary = tmp_path / "acp-supervisor.exe"
    binary.write_bytes(b"actual")
    manifest = manifest_for(binary, sha256_bytes(b"expected"))

    with pytest.raises(
        AuthorityValidationError,
        match="SHA-256 mismatch",
    ):
        WindowsScmBinaryVerifier().verify(manifest)


@pytest.mark.skipif(os.name != "nt", reason="Windows-only on-disk verification")
def test_missing_binary_fails_closed(tmp_path):
    binary = tmp_path / "missing.exe"
    manifest = manifest_for(binary, sha256_bytes(b"anything"))

    with pytest.raises(
        AuthorityValidationError,
        match="does not exist",
    ):
        WindowsScmBinaryVerifier().verify(manifest)


@pytest.mark.skipif(os.name != "nt", reason="Windows-only on-disk verification")
def test_mutated_binary_no_longer_matches_manifest(tmp_path):
    binary = tmp_path / "acp-supervisor.exe"
    original = b"original"
    binary.write_bytes(original)
    manifest = manifest_for(binary, sha256_bytes(original))

    verifier = WindowsScmBinaryVerifier()
    assert verifier.verify(manifest).matched is True

    binary.write_bytes(b"modified")
    with pytest.raises(
        AuthorityValidationError,
        match="SHA-256 mismatch",
    ):
        verifier.verify(manifest)


@pytest.mark.skipif(os.name != "nt", reason="Windows-only on-disk verification")
def test_composed_registration_admission_binds_manifest_and_disk(tmp_path):
    binary = tmp_path / "acp-supervisor.exe"
    payload = b"approved binary"
    binary.write_bytes(payload)
    manifest = manifest_for(binary, sha256_bytes(payload))

    admission = WindowsScmServiceRegistrationAdmission(
        policy=policy_for(manifest),
    )
    result = admission.assert_admitted(manifest)

    assert result.manifest_sha256 == manifest.content_sha256()
    assert result.binary.actual_sha256 == manifest.binary_sha256


@pytest.mark.skipif(os.name == "nt", reason="Non-Windows fail-closed behavior")
def test_on_disk_verification_fails_closed_off_windows():
    manifest = WindowsScmServiceRegistrationManifest(
        service_name="ACPAgentControlPlane",
        display_name="ACP Agent Control Plane",
        binary_path=r"C:\ACP\acp-supervisor.exe",
        account_name=r"NT SERVICE\ACPAgentControlPlane",
        binary_sha256="a" * 64,
    )
    with pytest.raises(
        AuthorityValidationError,
        match="requires Windows",
    ):
        WindowsScmBinaryVerifier().verify(manifest)
