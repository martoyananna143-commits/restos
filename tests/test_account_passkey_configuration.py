"""Focused production configuration tests for Stage 22A WebAuthn."""

import pytest
from environs import EnvError

from app.settings import Config


def _production_environment(monkeypatch, **changes):
    values = {
        "APP_ENV": "production",
        "TGBOT_TOKEN": "test-only-token",
        "TGBOT_ADMIN_IDS": "0",
        "JWT_SECRET_KEY": "j" * 48,
        "WEBAPP_SECRET_KEY": "a" * 64,
        "DEFAULT_ADMIN_PASSWORD": "Strong-Test-Password-42!",
        "INTERNAL_API_KEY": "i" * 48,
        "CORS_ORIGINS": "https://api.example.test",
        "CORS_ALLOW_CREDENTIALS": "true",
        "SMS_PROVIDER": "disabled",
        "ACCOUNT_GROUP_INVITATION_PEPPER": "g" * 48,
        "WEBAUTHN_RP_ID": "example.test",
        "WEBAUTHN_RP_NAME": "RestOS",
        "WEBAUTHN_ALLOWED_ORIGINS": "https://example.test",
        "WEBAUTHN_CHALLENGE_TTL_SECONDS": "300",
        "WEBAUTHN_MAX_VERIFY_ATTEMPTS": "3",
    }
    values.update(changes)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize(
    "origin",
    ["https://example.test", "https://app.example.test"],
)
def test_valid_production_webauthn_configuration(monkeypatch, origin):
    _production_environment(monkeypatch, WEBAUTHN_ALLOWED_ORIGINS=origin)
    Config().validate_production_security()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("WEBAUTHN_RP_ID", ""),
        ("WEBAUTHN_RP_ID", "https://example.test"),
        ("WEBAUTHN_RP_ID", "example.test:443"),
        ("WEBAUTHN_RP_ID", "example.test/path"),
        ("WEBAUTHN_RP_ID", "user@example.test"),
        ("WEBAUTHN_RP_NAME", ""),
        ("WEBAUTHN_ALLOWED_ORIGINS", ""),
        ("WEBAUTHN_ALLOWED_ORIGINS", "http://example.test"),
        ("WEBAUTHN_ALLOWED_ORIGINS", "https://*.example.test"),
        ("WEBAUTHN_ALLOWED_ORIGINS", "https://example.test?query=1"),
        ("WEBAUTHN_ALLOWED_ORIGINS", "https://example.test#fragment"),
        ("WEBAUTHN_ALLOWED_ORIGINS", "https://user@example.test"),
        ("WEBAUTHN_ALLOWED_ORIGINS", "https://unrelated.test"),
        ("WEBAUTHN_CHALLENGE_TTL_SECONDS", "0"),
        ("WEBAUTHN_CHALLENGE_TTL_SECONDS", "-1"),
        ("WEBAUTHN_CHALLENGE_TTL_SECONDS", "601"),
        ("WEBAUTHN_MAX_VERIFY_ATTEMPTS", "0"),
        ("WEBAUTHN_MAX_VERIFY_ATTEMPTS", "-1"),
        ("WEBAUTHN_MAX_VERIFY_ATTEMPTS", "11"),
    ],
)
def test_invalid_production_webauthn_configuration(monkeypatch, name, value):
    _production_environment(monkeypatch, **{name: value})
    with pytest.raises(RuntimeError) as caught:
        Config().validate_production_security()
    message = str(caught.value)
    if value:
        assert value not in message
    else:
        assert message
        assert "Production security checks failed" in message
        lowered = message.lower()
        for forbidden in (
            "traceback",
            "credential",
            "private key",
            "challenge_digest",
            "refresh_token",
            "jwt_secret_key",
            "webapp_secret_key",
            "internal_api_key",
            "test-only-token",
        ):
            assert forbidden not in lowered


@pytest.mark.parametrize(
    "name",
    ["WEBAUTHN_CHALLENGE_TTL_SECONDS", "WEBAUTHN_MAX_VERIFY_ATTEMPTS"],
)
def test_non_integer_webauthn_limits_are_rejected(monkeypatch, name):
    invalid_value = "not-an-integer-stage22a"
    _production_environment(monkeypatch, **{name: invalid_value})
    with pytest.raises(EnvError) as caught:
        Config()
    assert invalid_value not in str(caught.value)
