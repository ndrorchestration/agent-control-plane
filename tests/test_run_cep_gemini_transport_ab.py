import importlib.util
import json
from pathlib import Path


SCRIPT = Path("scripts/run_cep_gemini_transport_ab.py")
SPEC = importlib.util.spec_from_file_location("cep_gemini_ab", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeEncoding:
    def encode(self, text):
        return list(text.encode("utf-8"))


class FakeTokenizer:
    __version__ = "test"

    @staticmethod
    def get_encoding(name):
        assert name == "o200k_base"
        return FakeEncoding()


FAKE_TOKENIZER = FakeTokenizer()


def exploding_opener(*args, **kwargs):
    raise AssertionError("network transport must not be called")


def test_default_dry_run_does_not_read_credential_or_send() -> None:
    result = MODULE.run_pair(
        send=False,
        environ={"GEMINI_API_KEY": "must-not-be-read"},
        opener=exploding_opener,
    )

    assert result["status"] == "BLOCKED_SEND_NOT_REQUESTED"
    assert result["credential_read"] is False
    assert result["control"]["sent"] is False
    assert result["treatment"]["sent"] is False
    assert result["scientific_n_increment"] == 0
    assert result["efficacy_effect"] == "NONE"
    assert "must-not-be-read" not in json.dumps(result)


def test_send_without_credential_fails_closed_before_network() -> None:
    result = MODULE.run_pair(
        send=True,
        environ={},
        opener=exploding_opener,
    )

    assert result["status"] == "BLOCKED_CREDENTIAL_NOT_CONFIGURED"
    assert result["credential_read"] is True
    assert result["credential_env"] == "GEMINI_API_KEY"
    assert result["control"]["sent"] is False
    assert result["treatment"]["sent"] is False


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def expected_tool_opener(req, timeout):
    body = json.loads(req.data.decode("utf-8"))
    selected_alias = None
    for item in body["tools"]:
        description = item["function"]["description"]
        if MODULE.EXPECTED_TOOL in description:
            selected_alias = item["function"]["name"]
            break
    assert selected_alias is not None
    assert req.headers["Authorization"] == "Bearer ephemeral-secret"
    return FakeResponse(
        {
            "id": "provider-request-observed",
            "model": "gemini-3.8-flash",
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {"function": {"name": selected_alias}}
                        ]
                    }
                }
            ],
        }
    )


def test_valid_frozen_pair_reaches_transport_ready_only() -> None:
    result = MODULE.run_pair(
        send=True,
        environ={"GEMINI_API_KEY": "ephemeral-secret"},
        opener=expected_tool_opener,
        tokenizer=FAKE_TOKENIZER,
    )

    assert result["status"] == "TRANSPORT_PAIR_READY_FOR_RESULT_ADJUDICATION"
    assert result["control"]["model_visible_exposure_observed"] is True
    assert result["treatment"]["model_visible_exposure_observed"] is True
    assert result["control"]["selected_tool"] == MODULE.EXPECTED_TOOL
    assert result["treatment"]["selected_tool"] == MODULE.EXPECTED_TOOL
    assert result["control"]["model_visible_tool_tokens"] > (
        result["treatment"]["model_visible_tool_tokens"]
    )
    assert result["treatment"]["model_visible_tool_tokens"] > 0
    assert result["control"]["model_visible_tool_token_basis"] == (
        "TOKENIZED_EXACT_SENT_TOOLS_JSON"
    )
    assert result["treatment"]["model_visible_tool_token_basis"] == (
        "TOKENIZED_EXACT_SENT_TOOLS_JSON"
    )
    assert result["control"]["catalog_sha256"] == MODULE.EXPECTED_CONTROL_SHA
    assert result["treatment"]["catalog_sha256"] == MODULE.EXPECTED_TREATMENT_SHA
    assert result["execution_effect"] == "NONE"
    assert result["routing_effect"] == "NONE"
    assert "ephemeral-secret" not in json.dumps(result)


def provider_without_tool_call(req, timeout):
    return FakeResponse(
        {
            "id": "provider-request-no-tool",
            "model": "gemini-3.8-flash",
            "choices": [{"message": {"content": "no tool"}}],
        }
    )


def test_provider_identity_without_tool_call_remains_unobserved() -> None:
    result = MODULE.run_pair(
        send=True,
        environ={"GEMINI_API_KEY": "ephemeral-secret"},
        opener=provider_without_tool_call,
        tokenizer=FAKE_TOKENIZER,
    )

    assert result["status"] == "BLOCKED_DYNAMIC_EXPOSURE_UNOBSERVED"
    assert result["control"]["model_visible_exposure_observed"] is False
    assert result["treatment"]["model_visible_exposure_observed"] is False
    assert result["control"]["model_visible_tool_tokens"] is None
    assert result["treatment"]["model_visible_tool_tokens"] is None


def first_tool_opener(req, timeout):
    body = json.loads(req.data.decode("utf-8"))
    selected_alias = body["tools"][0]["function"]["name"]
    return FakeResponse(
        {
            "id": "provider-request-first-tool",
            "model": "gemini-3.8-flash",
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {"function": {"name": selected_alias}}
                        ]
                    }
                }
            ],
        }
    )


def test_wrong_control_tool_selection_blocks_pair() -> None:
    result = MODULE.run_pair(
        send=True,
        environ={"GEMINI_API_KEY": "ephemeral-secret"},
        opener=first_tool_opener,
        tokenizer=FAKE_TOKENIZER,
    )

    assert result["control"]["model_visible_exposure_observed"] is True
    assert result["treatment"]["model_visible_exposure_observed"] is True
    assert result["treatment"]["selected_tool"] == MODULE.EXPECTED_TOOL
    assert result["control"]["selected_tool"] != MODULE.EXPECTED_TOOL
    assert result["status"] == "BLOCKED_SELECTED_TOOL_NOT_PRESERVED"


def test_treatment_first_order_is_recorded_without_changing_pair_identity() -> None:
    result = MODULE.run_pair(
        send=True,
        environ={"GEMINI_API_KEY": "ephemeral-secret"},
        opener=expected_tool_opener,
        order=("treatment", "control"),
        tokenizer=FAKE_TOKENIZER,
    )

    assert result["order"] == ["treatment", "control"]
    assert result["status"] == "TRANSPORT_PAIR_READY_FOR_RESULT_ADJUDICATION"
