"""Filter for checking administrator employee type."""

from typing import Union

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message
from dependency_injector.wiring import Provide, inject

from app.internal import Container
from app.internal.services.employee_service import EmployeeService


class IsAdministratorFilter(BaseFilter):
    """Filter to check if user has administrator employee type."""

    @inject
    async def __call__(
        self,
        obj: Union[Message, CallbackQuery],
        employee_service: EmployeeService = Provide[Container.employee_service],
    ) -> bool:
        """Check if user is administrator.

        Args:
            obj: Message or CallbackQuery object.
            employee_service: Employee service instance (injected).

        Returns:
            True if user is administrator, False otherwise.
        """
        telegram_id = None
        if isinstance(obj, Message) and obj.from_user:
            telegram_id = obj.from_user.id
        elif isinstance(obj, CallbackQuery) and obj.from_user:
            telegram_id = obj.from_user.id

        if not telegram_id:
            return False

        employee = await employee_service.get_by_telegram_id(telegram_id)
        if not employee:
            return False

        # Check if employee_type_code is 'administrator'
        employee_type_code = employee.meta.get("employee_type_code")
        return employee_type_code == "administrator"

