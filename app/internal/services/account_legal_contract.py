"""Immutable P0-LEGAL versions and document hashes approved for Account auth."""

from __future__ import annotations

from dataclasses import dataclass


DOCUMENT_SET_VERSION = "restos-account-legal-2026-08-10-v1"
PRIVACY_VERSION = "restos-privacy-2026-08-10-v1"
PD_CONSENT_VERSION = "restos-pd-consent-2026-08-10-v1"
TERMS_VERSION = "restos-terms-2026-08-10-v1"
AUTH_SMS_CONSENT_VERSION = "restos-auth-sms-consent-2026-08-10-v1"

PRIVACY_DOCUMENT_SHA256 = bytes.fromhex(
    "1440f6340a6f27dee5d650d1e52548dfcf2cef981e1fa707228854a1c4fb82be"
)
PD_CONSENT_DOCUMENT_SHA256 = bytes.fromhex(
    "e6b7ccec04eee2fecf023fe5d69b34eb24411cd46a639e9736921996db8fc172"
)
TERMS_DOCUMENT_SHA256 = bytes.fromhex(
    "89bdacb8131584b0cd6da0dcb0aeadeb3374928a969a4f3649f161e865a5b0aa"
)
REGISTRATION_SMS_COPY_SHA256 = bytes.fromhex(
    "75fa1c389221097f453d7e44f4a5e471f7330b3156fba1d6ea67d5c58777d5f5"
)
PASSWORD_RECOVERY_SMS_COPY_SHA256 = bytes.fromhex(
    "5e4ca8f9056e48d167d9ee099fee42d3b27f2eb62e9af53340dbe11afecd7b06"
)

ACCOUNT_REGISTRATION_CONTEXT = "account_registration"
REGISTRATION_OTP_MESSAGE_TYPE = "registration_otp"
PASSWORD_RECOVERY_OTP_MESSAGE_TYPE = "password_recovery_otp"


class AccountLegalVersionMismatch(ValueError):
    """The client did not submit the current immutable legal version."""


@dataclass(frozen=True)
class RegistrationSmsConsent:
    personal_data_consent: bool
    personal_data_consent_version: str
    authorization_sms_consent: bool
    authorization_sms_consent_version: str


@dataclass(frozen=True)
class AuthorizationSmsConsent:
    authorization_sms_consent: bool
    authorization_sms_consent_version: str


@dataclass(frozen=True)
class AccountRegistrationAcceptance:
    document_set_version: str
    terms_version: str
    privacy_version: str


def require_registration_sms_consent(
    consent: RegistrationSmsConsent,
) -> None:
    if (
        consent.personal_data_consent is not True
        or consent.authorization_sms_consent is not True
        or consent.personal_data_consent_version != PD_CONSENT_VERSION
        or consent.authorization_sms_consent_version != AUTH_SMS_CONSENT_VERSION
    ):
        raise AccountLegalVersionMismatch("registration consent is unavailable")


def require_authorization_sms_consent(
    consent: AuthorizationSmsConsent,
) -> None:
    if (
        consent.authorization_sms_consent is not True
        or consent.authorization_sms_consent_version != AUTH_SMS_CONSENT_VERSION
    ):
        raise AccountLegalVersionMismatch("SMS consent is unavailable")


def require_account_registration_acceptance(
    acceptance: AccountRegistrationAcceptance,
) -> None:
    if (
        acceptance.document_set_version != DOCUMENT_SET_VERSION
        or acceptance.terms_version != TERMS_VERSION
        or acceptance.privacy_version != PRIVACY_VERSION
    ):
        raise AccountLegalVersionMismatch("account legal version is unavailable")
