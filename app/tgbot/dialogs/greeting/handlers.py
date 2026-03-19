"""Handlers for greeting dialog."""

import logging

from aiogram.types import CallbackQuery
from aiogram.types import Message as MessageType
from aiogram_dialog import DialogManager, ShowMode, StartMode
from aiogram_dialog.widgets.kbd import Button
from dependency_injector.wiring import Provide, inject

from app.internal import Container
from app.internal.usecases.employee_service import EmployeeService
from app.internal.usecases.organization_service import OrganizationService
from app.settings import config
from app.tgbot.dialogs.criterion.states import CriterionDialog
from app.tgbot.dialogs.criterion_set.states import CriterionSetDialog
from app.tgbot.dialogs.employee.states import EmployeeDialog
from app.tgbot.dialogs.evaluation.states import EvaluationDialog
from app.tgbot.dialogs.organization.states import OrganizationDialog

logger = logging.getLogger(__name__)


async def _resolve_organization(telegram_id: int, organization_service, user_service):
    """Load active organization from DB: current_organization_id, then fallback to first by telegram_id."""
    user = await user_service.repository.get_by_telegram_id_any_chat(telegram_id)
    organization = None
    if user and getattr(user, "current_organization_id", None):
        organization = await organization_service.get_by_id(user.current_organization_id)
    if not organization:
        organization = await organization_service.get_by_user_telegram_id(telegram_id)
    return organization


def _is_superuser_telegram_id(telegram_id: int, user=None) -> bool:
    """Return True if this telegram_id belongs to a bot-level superuser."""
    if telegram_id in config.TGBOT_ADMIN_IDS:
        return True
    if user and getattr(user, "is_bot_administrator", False):
        return True
    return False


async def _start_with_org_skip(
    dialog_manager: DialogManager,
    telegram_id: int,
    org_state,
    next_state,
    organization,
    organization_service,
    user_service,
    on_success_callback=None,
    start_mode=StartMode.NORMAL,
    show_mode=None,
):
    """Start dialog, skipping org selection if org is already known.

    Superusers always go to org_state to pick which org to work with.
    Regular users: if org known — go directly to next_state; else — org_state.
    """
    user = dialog_manager.middleware_data.get("user")
    is_super = _is_superuser_telegram_id(telegram_id, user)

    if is_super:
        # Superuser always picks org from the full list
        start_kwargs = {"state": org_state, "mode": start_mode}
        if show_mode is not None:
            start_kwargs["show_mode"] = show_mode
        await dialog_manager.start(**start_kwargs)
        return

    if not organization:
        organization = await _resolve_organization(telegram_id, organization_service, user_service)

    if organization:
        dialog_manager.middleware_data["organization"] = organization
        start_kwargs = {"state": next_state, "mode": start_mode}
        if show_mode is not None:
            start_kwargs["show_mode"] = show_mode
        await dialog_manager.start(**start_kwargs)
        dialog_manager.dialog_data["organization_id"] = organization.id
        if on_success_callback:
            await on_success_callback(organization, dialog_manager)
    else:
        start_kwargs = {"state": org_state, "mode": start_mode}
        if show_mode is not None:
            start_kwargs["show_mode"] = show_mode
        await dialog_manager.start(**start_kwargs)


@inject
async def _check_administrator_access(
    callback: CallbackQuery,
    dialog_manager: DialogManager,
    employee_service: EmployeeService,
    organization_service: OrganizationService = Provide[Container.organization_service],
    user_service=Provide[Container.user_service],
) -> bool:
    """Check if user has administrator access in current organization.

    Three-tier check: TGBOT_ADMIN_IDS → is_bot_administrator → employee_type_code.
    """
    telegram_id = callback.from_user.id if callback.from_user else None
    if not telegram_id:
        return False

    if telegram_id in config.TGBOT_ADMIN_IDS:
        return True

    user = dialog_manager.middleware_data.get("user")
    if not user:
        user = await user_service.repository.get_by_telegram_id(telegram_id, 0)
        if user:
            dialog_manager.middleware_data["user"] = user

    if user and getattr(user, "is_bot_administrator", False):
        return True

    organization = dialog_manager.middleware_data.get("organization")
    organization_id = None
    if organization:
        organization_id = organization.id
    else:
        organization_id = dialog_manager.dialog_data.get("organization_id")
        if not organization_id:
            organization = await organization_service.get_by_user_telegram_id(telegram_id)
            if organization:
                organization_id = organization.id
                dialog_manager.middleware_data["organization"] = organization

    if not organization_id:
        return False

    employee = await employee_service.get_by_telegram_id_and_organization_id(
        telegram_id, organization_id
    )
    if not employee:
        return False

    return employee.meta.get("employee_type_code") == "administrator"


async def _get_telegram_id(callback: CallbackQuery, dialog_manager: DialogManager) -> int | None:
    if callback.from_user:
        return callback.from_user.id
    return dialog_manager.middleware_data.get("user_data", {}).get("telegram_id")


@inject
async def on_help_clicked(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
    user_service=Provide[Container.user_service],
):
    """Handle help button click.

    If user already has an organization (not first entry), notify all
    administrators of that organization about the help request.
    """
    from app.tgbot.dialogs.help.states import HelpDialog

    if callback.from_user:
        dialog_manager.middleware_data["user_data"] = {
            "first_name": callback.from_user.first_name or "Пользователь",
            "username": callback.from_user.username or "",
            "telegram_id": callback.from_user.id,
        }

    telegram_id = callback.from_user.id if callback.from_user else None

    # Notify admins only when this is NOT the first/onboarding call
    # (first-entry help is launched from start_handler without an org).
    if telegram_id:
        organization = dialog_manager.middleware_data.get("organization")
        if not organization:
            organization = await _resolve_organization(telegram_id, organization_service, user_service)

        if organization:
            requester_name = (
                callback.from_user.first_name or "Пользователь"
            ) if callback.from_user else "Пользователь"
            requester_username = (
                f" (@{callback.from_user.username})" if callback.from_user and callback.from_user.username else ""
            )

            employees = await employee_service.get_by_organization_id(organization.id)
            admin_telegram_ids = [
                emp.telegram_id
                for emp in employees
                if emp.employee_type_id == 3
                and emp.telegram_id
                and emp.telegram_id != telegram_id
            ]

            if admin_telegram_ids:
                bot = dialog_manager.middleware_data.get("bot") or getattr(dialog_manager.event, "bot", None)
                if bot:
                    notification = (
                        f"🆘 <b>Запрос помощи</b>\n\n"
                        f"👤 Пользователь: <b>{requester_name}</b>{requester_username}\n"
                        f"🏢 Организация: <b>{organization.name}</b>\n\n"
                        f"Сотрудник нажал кнопку «Помощь» и нуждается в поддержке."
                    )
                    for admin_id in admin_telegram_ids:
                        try:
                            await bot.send_message(admin_id, notification, parse_mode="HTML")
                        except Exception:
                            pass

    await dialog_manager.start(HelpDialog.main_help)


@inject
async def on_edit_employee_clicked(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
    user_service=Provide[Container.user_service],
):
    """Handle edit employee button click."""
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "У вас нет прав доступа для управления сотрудниками."
            )
        return

    telegram_id = await _get_telegram_id(callback, dialog_manager)
    if not telegram_id:
        await dialog_manager.start(EmployeeDialog.select_organization_for_edit)
        return

    from app.tgbot.dialogs.employee.windows import _on_employee_org_success
    await _start_with_org_skip(
        dialog_manager, telegram_id,
        org_state=EmployeeDialog.select_organization_for_edit,
        next_state=EmployeeDialog.select_employee_to_edit,
        organization=None,
        organization_service=organization_service,
        user_service=user_service,
        on_success_callback=_on_employee_org_success,
    )


@inject
async def on_create_employee_clicked(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
    user_service=Provide[Container.user_service],
):
    """Handle create employee button click."""
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "У вас нет прав доступа для управления сотрудниками."
            )
        return

    telegram_id = await _get_telegram_id(callback, dialog_manager)
    if not telegram_id:
        await dialog_manager.start(state=EmployeeDialog.select_organization)
        return

    from app.tgbot.dialogs.employee.windows import _on_employee_org_success
    organization = await _resolve_organization(telegram_id, organization_service, user_service)
    if not organization:
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "Для создания сотрудника необходимо сначала создать организацию."
            )
        await dialog_manager.start(OrganizationDialog.check_organization, mode=StartMode.RESET_STACK)
        return

    await _start_with_org_skip(
        dialog_manager, telegram_id,
        org_state=EmployeeDialog.select_organization,
        next_state=EmployeeDialog.full_name_input,
        organization=organization,
        organization_service=organization_service,
        user_service=user_service,
        on_success_callback=_on_employee_org_success,
    )


@inject
async def on_create_criterion_clicked(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
    user_service=Provide[Container.user_service],
):
    """Handle create criterion button click."""
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "У вас нет прав доступа для управления критериями."
            )
        return

    telegram_id = await _get_telegram_id(callback, dialog_manager)
    if not telegram_id:
        await dialog_manager.start(state=CriterionDialog.select_organization, mode=StartMode.NORMAL, show_mode=ShowMode.EDIT)
        return

    organization = await _resolve_organization(telegram_id, organization_service, user_service)
    if not organization:
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "Для создания критерия необходимо сначала создать организацию."
            )
        await dialog_manager.start(OrganizationDialog.check_organization, mode=StartMode.RESET_STACK)
        return

    await _start_with_org_skip(
        dialog_manager, telegram_id,
        org_state=CriterionDialog.select_organization,
        next_state=CriterionDialog.select_criterion,
        organization=organization,
        organization_service=organization_service,
        user_service=user_service,
        start_mode=StartMode.NORMAL,
        show_mode=ShowMode.EDIT,
    )


@inject
async def on_create_criterion_set_clicked(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
    user_service=Provide[Container.user_service],
):
    """Handle create criterion set button click."""
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "У вас нет прав доступа для управления наборами критериев."
            )
        return

    telegram_id = await _get_telegram_id(callback, dialog_manager)
    if not telegram_id:
        await dialog_manager.start(state=CriterionSetDialog.select_organization)
        return

    organization = await _resolve_organization(telegram_id, organization_service, user_service)
    if not organization:
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "Для создания набора критериев необходимо сначала создать организацию."
            )
        await dialog_manager.start(OrganizationDialog.check_organization, mode=StartMode.RESET_STACK)
        return

    await _start_with_org_skip(
        dialog_manager, telegram_id,
        org_state=CriterionSetDialog.select_organization,
        next_state=CriterionSetDialog.select_set,
        organization=organization,
        organization_service=organization_service,
        user_service=user_service,
    )


@inject
async def on_create_evaluation_clicked(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    organization_service: OrganizationService = Provide[Container.organization_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
    user_service=Provide[Container.user_service],
):
    """Handle create evaluation button click."""
    telegram_id = await _get_telegram_id(callback, dialog_manager)

    if telegram_id:
        user = await user_service.repository.get_by_telegram_id_any_chat(telegram_id)  # type: ignore[union-attr]
        is_super = _is_superuser_telegram_id(telegram_id, user)

        if is_super:
            # Superuser picks any org; show the org-selection window
            await dialog_manager.start(state=EvaluationDialog.select_evaluation_type)
            return

        user_organizations = await organization_service.get_all_by_user_telegram_id(telegram_id)
        if not user_organizations:
            if callback.message and isinstance(callback.message, MessageType):
                await callback.message.answer(
                    "Для создания замера необходимо сначала создать организацию."
                )
            await dialog_manager.start(OrganizationDialog.check_organization, mode=StartMode.RESET_STACK)
            return

        # Активная организация только из БД (any chat — в callback chat_id может не совпадать с записью)
        logger.info("[create_eval] user_id=%s current_organization_id=%s", user.id if user else None, getattr(user, "current_organization_id", None) if user else None)
        organization = None
        if user and getattr(user, "current_organization_id", None):
            organization = await organization_service.get_by_id(user.current_organization_id)
        if not organization:
            organization = user_organizations[0]
        logger.info("[create_eval] org_id=%s", organization.id if organization else None)
        organization_ids = [org.id for org in user_organizations]
        dialog_manager.dialog_data["user_organization_ids"] = organization_ids

        is_administrator = False
        employee = await employee_service.get_by_telegram_id_and_organization_id(
            telegram_id, organization.id
        )
        if employee:
            is_administrator = employee.meta.get("employee_type_code") == "administrator"

        dialog_manager.middleware_data["organization"] = organization
        await dialog_manager.start(state=EvaluationDialog.select_evaluation_type)
        dialog_manager.dialog_data["organization_id"] = organization.id

        if not is_administrator and employee:
            dialog_manager.dialog_data["filled_by_employee_id"] = employee.id
            dialog_manager.dialog_data["filled_by_employee_name"] = employee.full_name
    else:
        await dialog_manager.start(state=EvaluationDialog.select_evaluation_type)


@inject
async def on_delete_evaluation_clicked(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    organization_service: OrganizationService = Provide[Container.organization_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
):
    """Handle delete evaluation button click."""
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "У вас нет прав доступа для удаления замеров."
            )
        return

    telegram_id = await _get_telegram_id(callback, dialog_manager)
    if telegram_id:
        organization = await organization_service.get_by_user_telegram_id(telegram_id)
        if not organization:
            if callback.message and isinstance(callback.message, MessageType):
                await callback.message.answer("Организация не найдена.")
            await dialog_manager.start(OrganizationDialog.check_organization, mode=StartMode.RESET_STACK)
            return

        dialog_manager.middleware_data["organization"] = organization
        dialog_manager.dialog_data["organization_id"] = organization.id

    await dialog_manager.start(
        state=EvaluationDialog.select_evaluation_to_delete,
        mode=StartMode.NORMAL,
    )


@inject
async def on_invite_admin(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    invitation_service=Provide[Container.invitation_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
):
    """Handle invite admin button click (superuser only)."""
    from app.tgbot.dialogs.greeting.states import GreetingDialog

    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "У вас нет прав для приглашения администраторов."
            )
        return

    inviter_telegram_id = await _get_telegram_id(callback, dialog_manager)
    if not inviter_telegram_id:
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: не удалось определить пользователя")
        return

    try:
        code = await invitation_service.create_invitation(
            inviter_telegram_id=inviter_telegram_id,
            organization_id=None,
            invitation_type="admin",
        )
        bot = dialog_manager.event.bot
        if bot is None:
            if callback.message and isinstance(callback.message, MessageType):
                await callback.message.answer("Ошибка: не удалось получить информацию о боте")
            return
        bot_info = await bot.get_me()
        invitation_link = f"https://t.me/{bot_info.username}?start={code}"

        dialog_manager.dialog_data["invitation_code"] = code
        dialog_manager.dialog_data["invitation_link"] = invitation_link

        await dialog_manager.switch_to(GreetingDialog.invite_admin)
    except Exception as e:
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(f"Ошибка при создании приглашения: {str(e)}")


INVITE_ROLE_MAP = {
    "1": {"id": 1, "code": "employee", "name": "Сотрудник"},
    "2": {"id": 2, "code": "manager", "name": "Менеджер"},
    "3": {"id": 3, "code": "administrator", "name": "Администратор"},
}


@inject
async def on_invite_to_org(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    organization_service: OrganizationService = Provide[Container.organization_service],
    user_service=Provide[Container.user_service],
):
    """First step: go to role selection before generating invite link."""
    from app.tgbot.dialogs.greeting.states import GreetingDialog

    telegram_id = await _get_telegram_id(callback, dialog_manager)
    if not telegram_id:
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: не удалось определить пользователя")
        return

    organization = dialog_manager.middleware_data.get("organization")
    if not organization:
        organization = await _resolve_organization(telegram_id, organization_service, user_service)
        if organization:
            dialog_manager.middleware_data["organization"] = organization

    if not organization:
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "Для создания ссылки-приглашения необходимо состоять в организации."
            )
        return

    await dialog_manager.switch_to(GreetingDialog.select_invite_role)


@inject
async def on_select_invite_role(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
    invitation_service=Provide[Container.invitation_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
    user_service=Provide[Container.user_service],
):
    """Handle role selection — save chosen role and generate invite link."""
    from app.tgbot.dialogs.greeting.states import GreetingDialog

    await callback.answer()

    role_id_str = str(item_id) if item_id is not None else None
    role = INVITE_ROLE_MAP.get(role_id_str) if role_id_str else None
    if role:
        dialog_manager.dialog_data["invite_employee_type_id"] = role["id"]
        dialog_manager.dialog_data["invite_role_name"] = role["name"]

    telegram_id = await _get_telegram_id(callback, dialog_manager)
    if not telegram_id:
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: не удалось определить пользователя.")
        return

    organization = dialog_manager.middleware_data.get("organization")
    if not organization:
        organization = await _resolve_organization(telegram_id, organization_service, user_service)
        if organization:
            dialog_manager.middleware_data["organization"] = organization

    if not organization:
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: организация не выбрана. Вернитесь в меню.")
        return

    employee_type_id = dialog_manager.dialog_data.get("invite_employee_type_id", 1)

    try:
        code = await invitation_service.create_invitation(
            inviter_telegram_id=telegram_id,
            organization_id=organization.id,
            invitation_type="employee",
            employee_type_id=employee_type_id,
        )
        bot = dialog_manager.event.bot
        if bot is None:
            if callback.message and isinstance(callback.message, MessageType):
                await callback.message.answer("Ошибка: не удалось получить информацию о боте")
            return
        bot_info = await bot.get_me()
        invitation_link = f"https://t.me/{bot_info.username}?start={code}"

        dialog_manager.dialog_data["invitation_code"] = code
        dialog_manager.dialog_data["invitation_link"] = invitation_link

        await dialog_manager.switch_to(GreetingDialog.invite_to_org)
    except Exception as e:
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(f"Ошибка при создании приглашения: {str(e)}")


@inject
async def on_switch_organization_selected(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
    organization_service: OrganizationService = Provide[Container.organization_service],
    user_service=Provide[Container.user_service],
):
    """Handle organization switch (superuser only)."""
    from app.tgbot.dialogs.greeting.states import GreetingDialog

    organization_id = int(item_id)
    organization = await organization_service.get_by_id(organization_id)

    if organization:
        dialog_manager.middleware_data["organization"] = organization
        # Clear per-org cached data so it reloads for the new org
        dialog_manager.middleware_data.pop("employee", None)
        dialog_manager.middleware_data.pop("is_administrator", None)
        dialog_manager.middleware_data.pop("is_manager", None)
        dialog_manager.middleware_data.pop("is_employee_only", None)

        # WHY: persist the choice to DB so that on the next /start the user
        # lands directly in this organization without seeing the selection screen.
        telegram_id = callback.from_user.id if callback.from_user else None
        if telegram_id:
            user = dialog_manager.middleware_data.get("user")
            if not user:
                user = await user_service.repository.get_by_telegram_id_any_chat(telegram_id)  # type: ignore[union-attr]
            if user:
                await user_service.repository.set_current_organization(user.id, organization_id)
                logger.info("[switch_org] SAVED current_organization_id=%s for user_id=%s", organization_id, user.id)
                # Update cached user object
                user.current_organization_id = organization_id
                dialog_manager.middleware_data["user"] = user

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                f"✅ Организация переключена на: {organization.name}"
            )
        await dialog_manager.switch_to(GreetingDialog.greeting)
    else:
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: организация не найдена")


async def on_start_work_clicked(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle start work button click."""
    await callback.answer("Начинаем работу!")
    if callback.from_user:
        dialog_manager.middleware_data["user_data"] = {
            "first_name": callback.from_user.first_name or "Пользователь",
            "username": callback.from_user.username or "",
            "telegram_id": callback.from_user.id,
        }


# =============================================================================
# WebApp button helpers — send InlineKeyboardMarkup with web_app
# =============================================================================

async def _send_webapp_button(
    callback: CallbackQuery,
    url: str,
    text: str,
    button_text: str,
):
    """Delegate to the shared webapp_helper that handles localhost fallback."""
    from app.tgbot.webapp_helper import send_webapp_or_link
    await send_webapp_or_link(
        message=callback.message if isinstance(callback.message, MessageType) else None,
        url=url,
        text=text,
        button_text=button_text,
    )


@inject
async def on_open_employees_webapp(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    organization_service: OrganizationService = Provide[Container.organization_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
    user_service=Provide[Container.user_service],
):
    """Open the employees page in Telegram Mini Web App."""
    from app.tgbot.webapp_helper import generate_page_url

    telegram_id = await _get_telegram_id(callback, dialog_manager)
    if not telegram_id:
        return

    user = dialog_manager.middleware_data.get("user")
    is_superuser = _is_superuser_telegram_id(telegram_id, user)

    if is_superuser:
        org_id = 0
    else:
        organization = dialog_manager.middleware_data.get("organization")
        if not organization and telegram_id:
            organization = await _resolve_organization(telegram_id, organization_service, user_service)

        if not organization:
            if callback.message and isinstance(callback.message, MessageType):
                await callback.message.answer("Организация не найдена.")
            return
        org_id = organization.id

    url = generate_page_url("employees", org_id, telegram_id)
    await _send_webapp_button(
        callback,
        url=url,
        text="👥 <b>Управление сотрудниками</b>\n\nОткройте Mini App для удобного просмотра и редактирования:",
        button_text="👥 Открыть список сотрудников",
    )
    await callback.answer()


@inject
async def on_open_my_evaluations_webapp(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    organization_service: OrganizationService = Provide[Container.organization_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
    user_service=Provide[Container.user_service],
):
    """Open the evaluations page in Telegram Mini Web App."""
    from app.tgbot.webapp_helper import generate_page_url

    telegram_id = await _get_telegram_id(callback, dialog_manager)
    if not telegram_id:
        return

    user = dialog_manager.middleware_data.get("user")
    is_superuser = _is_superuser_telegram_id(telegram_id, user)

    employee_id = None
    if is_superuser:
        # Superuser sees all evaluations across all orgs
        org_id = 0
    else:
        organization = dialog_manager.middleware_data.get("organization")
        if not organization and telegram_id:
            organization = await _resolve_organization(telegram_id, organization_service, user_service)

        if organization:
            employee = dialog_manager.middleware_data.get("employee")
            if not employee:
                employee = await employee_service.get_by_telegram_id_and_organization_id(
                    telegram_id, organization.id
                )
            if employee:
                employee_id = employee.id
            org_id = organization.id
        else:
            org_id = 0

    url = generate_page_url("evaluations", org_id, telegram_id, extra={"employee_id": employee_id})
    await _send_webapp_button(
        callback,
        url=url,
        text="📁 <b>Мои замеры</b>\n\nОткройте Mini App для просмотра всех ваших замеров:",
        button_text="📁 Открыть мои замеры",
    )
    await callback.answer()


@inject
async def on_open_analytics_webapp(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    organization_service: OrganizationService = Provide[Container.organization_service],
    user_service=Provide[Container.user_service],
):
    """Open the analytics page in Telegram Mini Web App."""
    from app.tgbot.webapp_helper import generate_page_url

    telegram_id = await _get_telegram_id(callback, dialog_manager)
    if not telegram_id:
        return

    user = dialog_manager.middleware_data.get("user")
    is_superuser = _is_superuser_telegram_id(telegram_id, user)

    if is_superuser:
        org_id = 0
    else:
        organization = dialog_manager.middleware_data.get("organization")
        if not organization:
            organization = await _resolve_organization(telegram_id, organization_service, user_service)

        if not organization:
            if callback.message and isinstance(callback.message, MessageType):
                await callback.message.answer("Организация не найдена.")
            return
        org_id = organization.id

    url = generate_page_url("analytics", org_id, telegram_id)
    await _send_webapp_button(
        callback,
        url=url,
        text="📈 <b>Аналитика</b>\n\nОткройте Mini App для подробного просмотра статистики:",
        button_text="📈 Открыть аналитику",
    )
    await callback.answer()


@inject
async def on_open_objects_analytics(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    organization_service: OrganizationService = Provide[Container.organization_service],
    user_service=Provide[Container.user_service],
):
    """Open bot-based analytics dialog at objects section (with org skip)."""
    from app.tgbot.dialogs.analytics.states import AnalyticsDialog

    telegram_id = await _get_telegram_id(callback, dialog_manager)
    if not telegram_id:
        await dialog_manager.start(state=AnalyticsDialog.select_organization)
        return

    await _start_with_org_skip(
        dialog_manager, telegram_id,
        org_state=AnalyticsDialog.select_organization,
        next_state=AnalyticsDialog.objects_select_type,
        organization=None,
        organization_service=organization_service,
        user_service=user_service,
    )
