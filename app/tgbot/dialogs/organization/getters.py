"""Getters for organization dialog."""

from dependency_injector.wiring import Provide, inject

from aiogram_dialog import DialogManager

from app.internal import Container
from app.internal.services.employee_service import EmployeeService
from app.internal.services.organization_service import OrganizationService
from app.tgbot.dialogs.common.utils import get_form_value


@inject
async def get_organizations_list_data(
    dialog_manager: DialogManager,
    organization_service: OrganizationService = Provide[Container.organization_service],
    *args,
    **kwargs,
):
    """Get data for organizations list window.

    Args:
        dialog_manager: Dialog manager instance.
        organization_service: Organization service instance (injected).
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with organizations list data.
    """
    user_data = dialog_manager.middleware_data.get("user_data", {})
    telegram_id = user_data.get("telegram_id")
    
    if not telegram_id:
        # Пытаемся получить из callback, если доступен
        event = dialog_manager.event
        if event and hasattr(event, "from_user") and event.from_user:
            telegram_id = event.from_user.id
    
    organizations = []
    if telegram_id:
        organizations = await organization_service.get_all_by_user_telegram_id(telegram_id)
    
    return {
        "organizations": organizations,
        "has_organizations": len(organizations) > 0,
    }


@inject
async def get_organization_check_data(
    dialog_manager: DialogManager,
    organization_service: OrganizationService = Provide[Container.organization_service],
    *args,
    **kwargs,
):
    """Get data for organization check window.

    Args:
        dialog_manager: Dialog manager instance.
        organization_service: Organization service instance (injected).
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with organization check data.
    """
    organization = dialog_manager.middleware_data.get("organization")
    
    if not organization:
        user_data = dialog_manager.middleware_data.get("user_data", {})
        telegram_id = user_data.get("telegram_id")
        if telegram_id:
            organization = await organization_service.get_by_user_telegram_id(telegram_id)
            if organization:
                dialog_manager.middleware_data["organization"] = organization
    
    has_not_organization = organization is None

    if not has_not_organization:
        org_name = getattr(organization, "name", "") if organization else ""
        message_text = f"Организация '{org_name}' уже создана."
    else:
        message_text = "У вас еще нет организации. Давайте создадим её!"

    return {
        "has_not_organization": has_not_organization,
        "organization_name": getattr(organization, "name", "") if organization else "",
        "message_text": message_text,
    }


async def get_organization_form_data(
    dialog_manager: DialogManager,
    *args,
    **kwargs,
):
    """Get data for organization form window.

    Args:
        dialog_manager: Dialog manager instance.
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with organization form data.
    """
    data = dialog_manager.dialog_data
    is_editing = bool(data.get("organization_id"))
    
    return {
        "name": get_form_value(data, "name", ""),
        "code": get_form_value(data, "code", ""),
        "address": get_form_value(data, "address", "Не указан"),
        "phone": get_form_value(data, "phone", "Не указан"),
        "is_editing": is_editing,
    }


@inject
async def get_employees_list_data_for_management(
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
    *args,
    **kwargs,
):
    """Get data for employees list window for management (including deleted).

    Args:
        dialog_manager: Dialog manager instance.
        employee_service: Employee service instance (injected).
        organization_service: Organization service instance (injected).
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with employees list data.
    """
    organization_id = dialog_manager.dialog_data.get("organization_id")
    
    # If organization_id not in dialog_data, try to get from middleware_data or load by user
    if not organization_id:
        organization = dialog_manager.middleware_data.get("organization")
        if organization:
            organization_id = organization.id
            dialog_manager.dialog_data["organization_id"] = organization_id
        else:
            # Try to load by user telegram_id
            user_data = dialog_manager.middleware_data.get("user_data", {})
            telegram_id = user_data.get("telegram_id")
            if telegram_id:
                organization = await organization_service.get_by_user_telegram_id(telegram_id)
                if organization:
                    organization_id = organization.id
                    dialog_manager.dialog_data["organization_id"] = organization_id
                    dialog_manager.middleware_data["organization"] = organization
    
    if not organization_id:
        return {
            "employees": [],
            "has_employees": False,
        }

    employees = await employee_service.get_by_organization_id_with_deleted(
        organization_id
    )

    # Разделяем на активных и уволенных
    active_employees = [emp for emp in employees if emp.deleted_at is None]
    fired_employees = [emp for emp in employees if emp.deleted_at is not None]

    # Формируем списки для отображения
    active_list = [
        {
            "id": emp.id,
            "full_name": emp.full_name,
            "position": emp.position or "Не указана",
            "display": f"{emp.full_name} - {emp.position or 'Не указана'}",
        }
        for emp in active_employees
    ]
    
    fired_list = [
        {
            "id": emp.id,
            "full_name": emp.full_name,
            "position": emp.position or "Не указана",
            "display": f"❌ {emp.full_name} - {emp.position or 'Не указана'} (Уволен)",
        }
        for emp in fired_employees
    ]

    # Check if this is first organization creation
    is_first_creation = dialog_manager.dialog_data.get("is_first_creation", False)
    
    return {
        "active_employees": active_list,
        "fired_employees": fired_list,
        "employees": active_list + fired_list,  # Для обратной совместимости
        "has_employees": len(active_list) > 0 or len(fired_list) > 0,
        "is_first_creation": is_first_creation,
    }


async def get_invitation_data(
    dialog_manager: DialogManager,
    *args,
    **kwargs,
):
    """Get data for invitation window.

    Args:
        dialog_manager: Dialog manager instance.
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with invitation data.
    """
    invitation_link = dialog_manager.dialog_data.get(
        "invitation_link", 
        "Создайте новую ссылку для приглашения"
    )
    
    # Check if this is first organization creation
    is_first_creation = dialog_manager.dialog_data.get("is_first_creation", False)
    
    return {
        "invitation_link": invitation_link,
        "is_first_creation": is_first_creation,
    }
