import pytest

from agent_control_plane.context_transport_profile import TransportProfile


def test_transport_profile_is_non_secret() -> None:
    profile = TransportProfile(
        profile_id="gemini-openai-compatible-v1",
        provider_family="google-gemini-openai-compatible",
        endpoint=(
            "https://generativelanguage.googleapis.com/"
            "v1beta/openai/chat/completions"
        ),
        model="gemini-3.8-flash",
        api_key_env="GEMINI_API_KEY",
        headers={"x-goog-api-client": "ndrorchestration-acp-cep/0.1.0"},
    )
    value = profile.to_mapping()

    assert value["api_key_env"] == "GEMINI_API_KEY"
    assert "api_key" not in value
    assert value["headers"]["x-goog-api-client"] == (
        "ndrorchestration-acp-cep/0.1.0"
    )


def test_transport_profile_rejects_authorization_header() -> None:
    with pytest.raises(ValueError, match="authorization"):
        TransportProfile(
            profile_id="bad",
            provider_family="provider",
            endpoint="https://example.test",
            model="model",
            api_key_env="API_KEY",
            headers={"Authorization": "Bearer secret"},
        )
