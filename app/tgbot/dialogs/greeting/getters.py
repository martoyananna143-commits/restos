"""Getters for greeting dialog."""

from aiogram_dialog import DialogManager
from dependency_injector.wiring import Provide, inject

from app.internal import Container
from app.internal.usecases.employee_service import EmployeeService
from app.internal.usecases.organization_service import OrganizationService
from app.settings import config


@inject
async def get_greeting_data(
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
    *args,
    **kwargs,
):
    """Get data for greeting window.

    Args:
        dialog_manager: Dialog manager instance.
        employee_service: Employee service instance (injected).
        organization_service: Organization service instance (injected).
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with greeting data.
    """

    telegram_id = dialog_manager.event.from_user.id

    user_name = dialog_manager.event.from_user.first_name
    username = dialog_manager.event.from_user.username

    # Check if user is in admin IDs (legacy check)
    is_admin = False
    if telegram_id:
        is_admin = telegram_id in config.TGBOT_ADMIN_IDS
        dialog_manager.middleware_data["is_admin"] = is_admin
    else:
        is_admin = dialog_manager.middleware_data.get("is_admin", False)

    # Check if user has administrator employee type in current organization
    is_administrator = False
    if telegram_id:
        # Get current organization
        organization = dialog_manager.middleware_data.get("organization")
        organization_id = None
        
        if organization:
            organization_id = organization.id
        else:
            organization = await organization_service.get_by_user_telegram_id(telegram_id)
            if organization:
                organization_id = organization.id
                dialog_manager.middleware_data["organization"] = organization
        
        if organization_id:
            employee = await employee_service.get_by_telegram_id_and_organization_id(
                telegram_id, organization_id
            )
            if employee:
                employee_type_code = employee.meta.get("employee_type_code")
                is_administrator = employee_type_code == "administrator"
                dialog_manager.middleware_data["is_administrator"] = is_administrator
                dialog_manager.middleware_data["employee"] = employee
    else:
        is_administrator = dialog_manager.middleware_data.get("is_administrator", False)

    greeting_text = f"Привет, {user_name}!"
    if username:
        greeting_text += f" (@{username})"

    return {
        "greeting_text": greeting_text,
        "user_name": user_name,
        "is_admin": is_admin,
        "is_administrator": is_administrator,
    }
