"""SMS Aero adapter for provider-neutral phone verification.

SMS Aero documents ``/v2/sms/send`` with HTTP Basic authentication using the
account email and API key, and a JSON response containing top-level ``success``
and ``data`` fields.  Credentials are sent only in the Authorization header.
The non-secret message fields use a POST form body so phone and OTP do not
appear in URLs.  No automatic retry is performed because an ambiguous network
failure may already have delivered the OTP.
"""

from __future__ import annotations

import re

import httpx

from app.internal.services.phone_verification_service import SmsDeliveryFailed


_E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")


class SmsAeroSender:
    """Send one verification SMS through SMS Aero without retries."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        email: str,
        api_key: str,
        sign: str,
        base_url: str,
        timeout_seconds: float,
    ):
        if not all(
            isinstance(value, str) and value.strip()
            for value in (email, api_key, sign, base_url)
        ):
            raise ValueError("SMS Aero configuration is incomplete")
        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise ValueError("SMS Aero timeout is invalid")
        self._client = client
        self._email = email.strip()
        self._api_key = api_key
        self._sign = sign.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout = float(timeout_seconds)

    async def send_verification_code(
        self,
        phone: str,
        code: str,
        purpose: str,
        expires_in_seconds: int,
        autofill_domain: str,
    ) -> None:
        if not _E164.fullmatch(phone):
            raise SmsDeliveryFailed("SMS delivery failed")
        number = phone[1:]
        text = f"Код RestOS: {code}\n@{autofill_domain} #{code}"
        try:
            response = await self._client.post(
                f"{self._base_url}/v2/sms/send",
                data={"number": number, "text": text, "sign": self._sign},
                auth=httpx.BasicAuth(self._email, self._api_key),
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.HTTPStatusError,
            ValueError,
        ) as error:
            raise SmsDeliveryFailed("SMS delivery failed") from error
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise SmsDeliveryFailed("SMS delivery failed")
