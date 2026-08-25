"""Provider-neutral employee invitation SMS delivery contract."""

from typing import Protocol


class EmployeeInvitationDeliveryFailed(Exception):
    """Provider gave a definitive non-delivery outcome; manual retry is safe."""


class EmployeeInvitationDeliveryUnknown(Exception):
    """Delivery may have occurred; automatic or manual resend is unsafe."""


class EmployeeInvitationSmsSender(Protocol):
    async def send_employee_invitation(
        self,
        phone: str,
        code: str,
        expires_in_seconds: int,
    ) -> None: ...
