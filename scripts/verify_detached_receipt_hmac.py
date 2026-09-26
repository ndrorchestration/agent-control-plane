from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_control_plane.remote_execution_adapter import (
    verify_detached_receipt_file_hmac,
)

receipt = Path(sys.argv[1])
signature = Path(sys.argv[2])
key = Path(sys.argv[3]).read_bytes()
verify_detached_receipt_file_hmac(receipt, signature, key=key)
print("DETACHED_RECEIPT_HMAC=PASS")
