from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_control_plane.remote_execution_adapter import (
    verify_receipt_signature_envelope,
)

receipt = Path(sys.argv[1])
envelope = Path(sys.argv[2])
key = Path(sys.argv[3]).read_bytes()
verify_receipt_signature_envelope(receipt, envelope, key=key)
print("RECEIPT_SIGNATURE_ENVELOPE=PASS")
