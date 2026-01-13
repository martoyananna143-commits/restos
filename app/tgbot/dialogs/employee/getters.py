"""Getters for employee dialog."""

from aiogram_dialog import DialogManager
from dependency_injector.wiring import Provide, inject

from app.internal import Container
from app.internal.usecases.employee_service import EmployeeService
from app.internal.usecases.organization_service import OrganizationService
from app.tgbot.dialogs.common.utils import get_form_value


async def get_employee_form_data(
    dialog_manager: DialogManager,
    *args,
    **kwargs,
):
    """Get data for employee form window.

    Args:
        dialog_manager: Dialog manager instance.
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with employee form data.
    """
    data = dialog_manager.dialog_data
    is_editing = bool(data.get("employee_id"))
    
    return {
        "full_name": get_form_value(data, "full_name", ""),
        "position": get_form_value(data, "position", "Не указана"),
        "phone": get_form_value(data, "phone", "Не указан"),
        "is_editing": is_editing,
    }


@inject
async def get_employees_list_data_for_edit(
    dialog_manager: DialogManager,
    organization_service: OrganizationService = Provide[Container.organization_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
    *args,
    **kwargs,
):
    """Get data for employees list window for editing.

    Args:
        dialog_manager: Dialog manager instance.
        organization_service: Organization service instance (injected).
        employee_service: Employee service instance (injected).
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with employees list data.
    """
    # Используем organization_id из dialog_data (установлен при выборе организации)
    organization_id = dialog_manager.dialog_data.get("organization_id")

    if not organization_id:
        # Fallback: пытаемся получить из middleware_data
        organization = dialog_manager.middleware_data.get("organization")
        if organization:
            organization_id = organization.id
            dialog_manager.dialog_data["organization_id"] = organization_id
        else:
            user_data = dialog_manager.middleware_data.get("user_data", {})
            telegram_id = user_data.get("telegram_id")

            if not telegram_id:
                event = dialog_manager.event
                if event and hasattr(event, "from_user") and event.from_user:
                    telegram_id = event.from_user.id

            if telegram_id:
                organization = await organization_service.get_by_user_telegram_id(
                    telegram_id
                )
                if organization:
                    organization_id = organization.id
                    dialog_manager.dialog_data["organization_id"] = organization_id
                    dialog_manager.middleware_data["organization"] = organization

    employees = []
    if organization_id:
        employees = await employee_service.get_by_organization_id(organization_id)
        # Фильтруем удаленных сотрудников
        employees = [emp for emp in employees if emp.deleted_at is None]

    return {
        "employees": employees,
        "has_employees": len(employees) > 0,
    }
