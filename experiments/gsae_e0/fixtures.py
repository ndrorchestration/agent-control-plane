"""Load and identify frozen GSAE-E0 fixture manifests deterministically."""

import hashlib
import json
from pathlib import Path

from .schema import FixtureManifest


def canonical_json_bytes(value: object) -> bytes:
    """Serialize JSON deterministically for content identity."""
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def load_fixture_manifest(path: Path) -> FixtureManifest:
    """Load and validate a fixture manifest from JSON."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return FixtureManifest.from_dict(data)


def fixture_manifest_sha256(path: Path) -> str:
    """Return SHA-256 of canonical validated fixture-manifest JSON."""
    data = json.loads(path.read_text(encoding="utf-8"))
    FixtureManifest.from_dict(data)
    return hashlib.sha256(canonical_json_bytes(data)).hexdigest()
