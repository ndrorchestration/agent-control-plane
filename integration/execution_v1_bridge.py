"""Synthetic, single-message, non-authorizing ACP event interchange CLI.

Invocation: python -m integration.execution_v1_bridge
Reads exactly one small JSON message from stdin and emits one JSON object to
stdout, or an error marker and exit code 2. Does NOT execute any event.
"""

import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from agent_control_plane.contract import ExecutionEvent
from integration.execution_v1_interop import from_cloudevent, to_cloudevent

MAX_BYTES = 65536
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "contracts" / "execution.v1.schema.json"


def _parse_input():
    data = sys.stdin.buffer.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("bounded input exceeded")
    decoded = json.loads(data.decode("utf-8"))
    if not isinstance(decoded, dict) or set(decoded) != {"operation", "payload"}:
        raise ValueError("malformed request")
    if decoded["operation"] not in ("encode", "decode"):
        raise ValueError("unsupported operation")
    return decoded


def _run(request):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    payload = request["payload"]
    if request["operation"] == "encode":
        validator.validate(payload)
        native = ExecutionEvent.from_dict(payload)
        if native.to_dict() != payload:
            raise ValueError("serialization mismatch")
        return to_cloudevent(native)

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise ValueError("malformed envelope data")
    validator.validate(payload["data"])
    native = from_cloudevent(payload)
    if native.to_dict() != payload["data"]:
        raise ValueError("decoded record mismatch")
    return native.to_dict()


def main():
    try:
        result = _run(_parse_input())
        response = json.dumps(
            result, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        sys.stdout.write(response + "\n")
    except (ValueError, TypeError, KeyError, UnicodeError, ValidationError):
        print("ACP_INTEROP_REJECTED", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
