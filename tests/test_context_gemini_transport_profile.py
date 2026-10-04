import json
from pathlib import Path

from agent_control_plane.context_transport_profile import TransportProfile


PROFILE = Path(
    "experiments/context_efficiency/transports/"
    "gemini-openai-compatible-v1.json"
)


def test_gemini_transport_profile_is_reproducible_and_non_secret() -> None:
    value = json.loads(PROFILE.read_text(encoding="utf-8"))
    profile = TransportProfile(
        profile_id=value["profile_id"],
        provider_family=value["provider_family"],
        endpoint=value["endpoint"],
        model=value["model"],
        api_key_env=value["api_key_env"],
        headers=value["headers"],
    )

    mapped = profile.to_mapping()
    assert mapped["endpoint"] == (
        "https://generativelanguage.googleapis.com/"
        "v1beta/openai/chat/completions"
    )
    assert mapped["model"] == "gemini-3.8-flash"
    assert mapped["api_key_env"] == "GEMINI_API_KEY"
    assert mapped["headers"] == {
        "x-goog-api-client": "ndrorchestration-acp-cep/0.1.0"
    }
