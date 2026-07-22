"""Getters for greeting dialog."""

from aiogram_dialog import DialogManager
from dependency_injector.wiring import Provide, inject

from app.internal import Container
from app.internal.services.employee_service import EmployeeService
from app.internal.services.evaluation_service import EvaluationService
from app.internal.services.organization_service import OrganizationService
from app.internal.services.user_service import UserService
from app.settings import config


def _is_superuser_check(telegram_id: int, user) -> bool:
    """Return True if the user is a bot-level superuser."""
    if telegram_id in config.TGBOT_ADMIN_IDS:
        return True
    if user and getattr(user, "is_bot_administrator", False):
        return True
    return False


@inject
async def get_greeting_data(
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
    user_service: UserService = Provide[Container.user_service],
    *args,
    **kwargs,
):
    """Get data for greeting window.

    Returns dict with role flags, org context and display text.
    """
    # Resolve telegram_id
    telegram_id = None
    if dialog_manager.event and hasattr(dialog_manager.event, "from_user") and dialog_manager.event.from_user:
        telegram_id = dialog_manager.event.from_user.id
        user_name = dialog_manager.event.from_user.first_name or "Пользователь"
        username = dialog_manager.event.from_user.username
    else:
        user_data = dialog_manager.middleware_data.get("user_data", {})
        telegram_id = user_data.get("telegram_id")
        user_name = user_data.get("first_name", "Пользователь")
        username = user_data.get("username")

    # --- Superuser check ---
    user = dialog_manager.middleware_data.get("user")
    if telegram_id and not user:
        user = await user_service.repository.get_by_telegram_id_any_chat(telegram_id)
        if user:
            dialog_manager.middleware_data["user"] = user

    is_superuser = _is_superuser_check(telegram_id, user) if telegram_id else False
    dialog_manager.middleware_data["is_admin"] = is_superuser
    dialog_manager.middleware_data["is_superuser"] = is_superuser

    # --- Organisation context ---
    organization = dialog_manager.middleware_data.get("organization")
    organization_id = None

    if not organization and telegram_id:
        if user and getattr(user, "current_organization_id", None):
            organization = await organization_service.get_by_id(user.current_organization_id)
        if not organization:
            organization = await organization_service.get_by_user_telegram_id(telegram_id)
        if organization:
            dialog_manager.middleware_data["organization"] = organization
            # Persist first-resolved org so subsequent dialogs can skip org selection
            if user and not getattr(user, "current_organization_id", None):
                await user_service.repository.set_current_organization(user.id, organization.id)
                user.current_organization_id = organization.id

    if organization:
        organization_id = organization.id

    organization_name = organization.name if organization else ""

    # --- Employee / org-role check ---
    is_administrator = False
    is_manager = False
    is_employee_only = False
    employee_type_code = None

    if telegram_id and organization_id:
        employee = dialog_manager.middleware_data.get("employee")
        if not employee or getattr(employee, "organization_id", None) != organization_id:
            employee = await employee_service.get_by_telegram_id_and_organization_id(
                telegram_id, organization_id
            )
            if employee:
                dialog_manager.middleware_data["employee"] = employee

        if employee:
            employee_type_code = employee.meta.get("employee_type_code")
            is_administrator = employee_type_code == "administrator"
            is_manager = employee_type_code == "manager"
            is_employee_only = employee_type_code == "employee"

            dialog_manager.middleware_data["is_administrator"] = is_administrator
            dialog_manager.middleware_data["is_manager"] = is_manager
            dialog_manager.middleware_data["is_employee_only"] = is_employee_only
    else:
        is_administrator = dialog_manager.middleware_data.get("is_administrator", False)
        is_manager = dialog_manager.middleware_data.get("is_manager", False)
        is_employee_only = dialog_manager.middleware_data.get("is_employee_only", False)

    # Superuser also counts as administrator for access control purposes
    if is_superuser:
        is_administrator = True

    # Derived permission flags
    # Менеджер и сотрудники могут создавать замеры; просматривают только свои (фильтр в get_by_employee_id).
    can_make_evaluation = is_superuser or is_administrator or is_manager or is_employee_only
    can_invite_to_org = is_superuser or is_administrator or is_manager

    # Build greeting text
    greeting_text = f"Привет, {user_name}!"
    if username:
        greeting_text += f" (@{username})"
    if not is_superuser and organization_name:
        greeting_text += f"\nОрганизация: {organization_name}"

    return {
        "greeting_text": greeting_text,
        "user_name": user_name,
        "organization_name": organization_name,
        # Role flags
        "is_superuser": is_superuser,
        "is_admin": is_superuser,
        "is_administrator": is_administrator,
        "is_manager": is_manager,
        "is_employee_only": is_employee_only,
        # Permission shortcuts
        "can_make_evaluation": can_make_evaluation,
        "can_invite_to_org": can_invite_to_org,
    }


@inject
async def get_employees_menu_data(
    dialog_manager: DialogManager,
    user_service: UserService = Provide[Container.user_service],
    *args,
    **kwargs,
):
    """Get data for employees menu window."""
    telegram_id = None
    if dialog_manager.event and hasattr(dialog_manager.event, "from_user") and dialog_manager.event.from_user:
        telegram_id = dialog_manager.event.from_user.id
    else:
        user_data = dialog_manager.middleware_data.get("user_data", {})
        telegram_id = user_data.get("telegram_id")

    is_bot_administrator = False
    if telegram_id:
        is_bot_administrator = telegram_id in config.TGBOT_ADMIN_IDS
        if not is_bot_administrator:
            user = await user_service.repository.get_by_telegram_id(telegram_id, 0)
            if user and getattr(user, "is_bot_administrator", False):
                is_bot_administrator = True

    return {
        "is_bot_administrator": is_bot_administrator,
    }


async def get_admin_invitation_data(
    dialog_manager: DialogManager,
    *args,
    **kwargs,
):
    """Get data for admin invitation window."""
    invitation_link = dialog_manager.dialog_data.get("invitation_link", "")
    return {
        "invitation_link": invitation_link,
    }


async def get_org_invitation_data(
    dialog_manager: DialogManager,
    *args,
    **kwargs,
):
    """Get data for invite-to-org window (manager / admin)."""
    invitation_link = dialog_manager.dialog_data.get("invitation_link", "")
    invite_role_name = dialog_manager.dialog_data.get("invite_role_name", "Сотрудник")
    organization_name = ""
    organization = dialog_manager.middleware_data.get("organization")
    if organization:
        organization_name = organization.name
    return {
        "invitation_link": invitation_link,
        "organization_name": organization_name,
        "invite_role_name": invite_role_name,
    }


@inject
async def get_my_evaluations_data(
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    evaluation_service: EvaluationService = Provide[Container.evaluation_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
    *args,
    **kwargs,
):
    """Get evaluations where the current employee participated."""
    telegram_id = None
    if dialog_manager.event and hasattr(dialog_manager.event, "from_user") and dialog_manager.event.from_user:
        telegram_id = dialog_manager.event.from_user.id
    else:
        user_data = dialog_manager.middleware_data.get("user_data", {})
        telegram_id = user_data.get("telegram_id")

    evaluations = []
    has_evaluations = False

    if telegram_id:
        organization = dialog_manager.middleware_data.get("organization")
        if not organization:
            organization = await organization_service.get_by_user_telegram_id(telegram_id)
            if organization:
                dialog_manager.middleware_data["organization"] = organization

        if organization:
            employee = dialog_manager.middleware_data.get("employee")
            if not employee:
                employee = await employee_service.get_by_telegram_id_and_organization_id(
                    telegram_id, organization.id
                )
                if employee:
                    dialog_manager.middleware_data["employee"] = employee

            if employee:
                evaluations = await evaluation_service.get_by_employee_id(employee.id)
                has_evaluations = len(evaluations) > 0

    return {
        "my_evaluations": evaluations,
        "has_evaluations": has_evaluations,
        "evaluations_count": len(evaluations),
    }


@inject
async def get_switch_organization_data(
    dialog_manager: DialogManager,
    organization_service: OrganizationService = Provide[Container.organization_service],
    *args,
    **kwargs,
):
    """Get organizations list for the switch-organization window (superuser)."""
    telegram_id = None
    if dialog_manager.event and hasattr(dialog_manager.event, "from_user") and dialog_manager.event.from_user:
        telegram_id = dialog_manager.event.from_user.id
    else:
        user_data = dialog_manager.middleware_data.get("user_data", {})
        telegram_id = user_data.get("telegram_id")

    organizations = []
    if telegram_id:
        organizations = await organization_service.get_all_by_user_telegram_id(telegram_id)

    has_organizations = len(organizations) > 0

    return {
        "organizations": organizations,
        "has_organizations": has_organizations,
        "no_organizations": not has_organizations,
    }
