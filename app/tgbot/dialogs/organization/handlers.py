"""Handlers for organization dialog."""

import logging

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button
from asyncpg import UniqueViolationError  # type: ignore
from dependency_injector.wiring import Provide, inject

from app.infra.database.repository.organization.dto import (
    CreateOrganizationDTO,
    UpdateOrganizationDTO,
)
from app.internal import Container
from app.internal.usecases.employee_service import EmployeeService
from app.internal.usecases.invitation_service import InvitationService
from app.internal.usecases.organization_service import OrganizationService
from app.settings import config
from app.tgbot.dialogs.organization.states import OrganizationDialog


@inject
async def _check_administrator_access(
    callback: CallbackQuery,
    dialog_manager: DialogManager,
    employee_service: EmployeeService,
    organization_service: OrganizationService = Provide[Container.organization_service],
    user_service = Provide[Container.user_service],
) -> bool:
    """Check if user has administrator access in current organization.

    First checks if user is in TGBOT_ADMIN_IDS from env (this takes precedence),
    then checks is_bot_administrator flag, then checks employee_type_code in organization.

    Args:
        callback: Callback query.
        dialog_manager: Dialog manager.
        employee_service: Employee service instance.
        organization_service: Organization service instance (injected).
        user_service: User service instance (injected).

    Returns:
        True if user is administrator in current organization, False otherwise.
    """
    telegram_id = None
    if callback.from_user:
        telegram_id = callback.from_user.id

    if not telegram_id:
        return False

    # First check: if user is in TGBOT_ADMIN_IDS, they have admin access regardless of employee_type
    if telegram_id in config.TGBOT_ADMIN_IDS:
        return True
    
    # Second check: check if user has is_bot_administrator flag
    user = dialog_manager.middleware_data.get("user")
    if not user:
        # Get user from repository
        user = await user_service.repository.get_by_telegram_id(telegram_id, 0)
        if user:
            dialog_manager.middleware_data["user"] = user
    
    if user and hasattr(user, 'is_bot_administrator') and user.is_bot_administrator:
        return True

    # Second check: check employee_type in organization
    # Get current organization from middleware_data or dialog_data
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

    employee_type_code = employee.meta.get("employee_type_code")
    return employee_type_code == "administrator"


async def on_skip_address(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle skip address button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    dialog_manager.dialog_data["address"] = None

    if dialog_manager.dialog_data.get("organization_id"):
        await dialog_manager.switch_to(OrganizationDialog.edit_menu)
    else:
        await dialog_manager.switch_to(OrganizationDialog.phone_input)


async def on_skip_phone(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle skip phone button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    dialog_manager.dialog_data["phone"] = None

    # Если редактируем существующую организацию, возвращаемся в меню редактирования
    if dialog_manager.dialog_data.get("organization_id"):
        await dialog_manager.switch_to(OrganizationDialog.edit_menu)
    else:
        await dialog_manager.switch_to(OrganizationDialog.confirm)


@inject
async def on_cancel(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Handle cancel button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        organization_service: Organization service instance (injected).
    """
    await callback.answer("Создание организации отменено")

    organization = dialog_manager.middleware_data.get("organization")

    if not organization:
        user_data = dialog_manager.middleware_data.get("user_data", {})
        telegram_id = user_data.get("telegram_id")

        if not telegram_id and callback.from_user:
            telegram_id = callback.from_user.id

        if telegram_id:
            organization = await organization_service.get_by_user_telegram_id(
                telegram_id
            )
            if organization:
                dialog_manager.middleware_data["organization"] = organization

    if organization:
        from app.tgbot.dialogs.greeting.states import GreetingDialog

        await dialog_manager.done()
    else:
        # Если организации нет, возвращаемся к окну проверки организации
        await dialog_manager.switch_to(
            OrganizationDialog.check_organization,
        )


@inject
async def on_select_organization_to_edit(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Handle organization selection for editing.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected organization ID.
        employee_service: Employee service instance (injected).
        organization_service: Organization service instance (injected).
    """
    
    # Check administrator access
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        from aiogram.types import Message as MessageType
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "❌ У вас нет прав доступа для управления организациями. "
                "Только администраторы могут редактировать организации."
            )
        return
    
    organization_id = int(item_id)

    organization = await organization_service.get_by_id(organization_id)
    if organization:
        dialog_manager.dialog_data["organization_id"] = organization_id
        dialog_manager.dialog_data["name"] = organization.name
        dialog_manager.dialog_data["code"] = organization.code
        dialog_manager.dialog_data["address"] = organization.address
        dialog_manager.dialog_data["phone"] = organization.phone
        await dialog_manager.switch_to(OrganizationDialog.edit_menu)
    else:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: организация не найдена")


# Edit menu handlers
@inject
async def on_edit_organization_name(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
):
    """Handle edit name button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        employee_service: Employee service instance (injected).
    """
    
    # Check administrator access
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        from aiogram.types import Message as MessageType
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "❌ У вас нет прав доступа для редактирования организаций."
            )
        return
    
    await dialog_manager.switch_to(OrganizationDialog.name_input)


@inject
async def on_edit_organization_code(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
):
    """Handle edit code button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        employee_service: Employee service instance (injected).
    """
    
    # Check administrator access
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        from aiogram.types import Message as MessageType
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "❌ У вас нет прав доступа для редактирования организаций."
            )
        return
    
    await dialog_manager.switch_to(OrganizationDialog.code_input)


@inject
async def on_edit_organization_address(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
):
    """Handle edit address button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        employee_service: Employee service instance (injected).
    """
    
    # Check administrator access
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        from aiogram.types import Message as MessageType
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "❌ У вас нет прав доступа для редактирования организаций."
            )
        return
    
    await dialog_manager.switch_to(OrganizationDialog.address_input)


@inject
async def on_edit_organization_phone(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
):
    """Handle edit phone button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        employee_service: Employee service instance (injected).
    """
    
    # Check administrator access
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        from aiogram.types import Message as MessageType
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "❌ У вас нет прав доступа для редактирования организаций."
            )
        return
    
    await dialog_manager.switch_to(OrganizationDialog.phone_input)


@inject
async def on_save_organization_changes(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
):
    """Handle save changes button click - goes to confirm window.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        employee_service: Employee service instance (injected).
    """
    
    # Check administrator access
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        from aiogram.types import Message as MessageType
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "❌ У вас нет прав доступа для сохранения изменений организаций."
            )
        return
    
    await dialog_manager.switch_to(OrganizationDialog.confirm)


@inject
async def on_manage_employees(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
):
    """Handle manage employees button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        employee_service: Employee service instance (injected).
    """
    
    # Check administrator access
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        from aiogram.types import Message as MessageType
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "❌ У вас нет прав доступа для управления сотрудниками. "
                "Только администраторы могут управлять сотрудниками."
            )
        return
    
    await dialog_manager.switch_to(OrganizationDialog.manage_employees)


@inject
async def on_fire_employee(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
    employee_service: EmployeeService = Provide[Container.employee_service],
):
    """Handle fire employee button click.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected employee ID.
        employee_service: Employee service instance (injected).
    """
    
    # Check administrator access
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        from aiogram.types import Message as MessageType
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "❌ У вас нет прав доступа для управления сотрудниками. "
                "Только администраторы могут увольнять сотрудников."
            )
        return
    
    employee_id = int(item_id)

    success = await employee_service.delete(employee_id)
    if success:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Сотрудник уволен.")
        # Обновляем список сотрудников
        await dialog_manager.switch_to(OrganizationDialog.manage_employees)
    else:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: не удалось уволить сотрудника.")


@inject
async def on_restore_employee(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
    employee_service: EmployeeService = Provide[Container.employee_service],
):
    """Handle restore employee button click.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected employee ID.
        employee_service: Employee service instance (injected).
    """
    
    # Check administrator access
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        from aiogram.types import Message as MessageType
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "❌ У вас нет прав доступа для управления сотрудниками."
            )
        return
    
    employee_id = int(item_id)

    success = await employee_service.restore(employee_id)
    if success:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.answer("Сотрудник восстановлен.")
        # Обновляем список сотрудников
        await dialog_manager.switch_to(OrganizationDialog.manage_employees)
    else:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.answer("Ошибка: не удалось восстановить сотрудника.")


@inject
async def on_confirm_organization(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    organization_service: OrganizationService = Provide[Container.organization_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
):
    """Handle confirm organization button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        organization_service: Organization service instance (injected).
        employee_service: Employee service instance (injected).
    """
    
    # Check administrator access for both create and update
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        from aiogram.types import Message as MessageType
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "❌ У вас нет прав доступа для управления организациями. "
                "Только администраторы могут создавать и редактировать организации."
            )
        return

    data = dialog_manager.dialog_data
    organization_id = data.get("organization_id")

    if organization_id:
        update_dto = UpdateOrganizationDTO(
            name=data["name"],
            code=data["code"],
            address=data.get("address"),
            phone=data.get("phone"),
        )
        organization = await organization_service.update(organization_id, update_dto)
        if organization:
            dialog_manager.middleware_data["organization"] = organization
            await callback.answer(
                f"Организация '{organization.name}' успешно обновлена!",
            )

            await dialog_manager.done()
            return
    else:
        create_dto = CreateOrganizationDTO(
            name=data["name"],
            code=data["code"],
            address=data.get("address"),
            phone=data.get("phone"),
        )
        try:
            organization = await organization_service.create(create_dto)
        except UniqueViolationError:
            from aiogram.types import Message as MessageType
            if callback.message and isinstance(callback.message, MessageType):
                msg: MessageType = callback.message
                await msg.answer(
                    "Нарушение уникальности, попробуйте изменить код или название организации",
                    show_alert=True,
                )
            return

    dialog_manager.middleware_data["organization"] = organization

    user_data = dialog_manager.middleware_data.get("user_data", {})
    telegram_id = user_data.get("telegram_id")

    if not telegram_id and callback.from_user:
        telegram_id = callback.from_user.id

    if not telegram_id and callback.message:
        from aiogram.types import Message as MessageType

        if isinstance(callback.message, MessageType) and callback.message.from_user:
            telegram_id = callback.message.from_user.id

    first_name = user_data.get("first_name")
    if not first_name:
        if callback.from_user:
            first_name = callback.from_user.first_name or "Пользователь"
        elif callback.message:
            from aiogram.types import Message as MessageType

            if isinstance(callback.message, MessageType) and callback.message.from_user:
                first_name = callback.message.from_user.first_name or "Пользователь"
            else:
                first_name = "Пользователь"
        else:
            first_name = "Пользователь"

    if telegram_id:
        username = user_data.get("username") or ""
        if callback.from_user and callback.from_user.username:
            username = callback.from_user.username
        elif callback.message:
            from aiogram.types import Message as MessageType

            if (
                isinstance(callback.message, MessageType)
                and callback.message.from_user
                and callback.message.from_user.username
            ):
                username = callback.message.from_user.username

        dialog_manager.middleware_data["user_data"] = {
            "first_name": first_name,
            "username": username,
            "telegram_id": telegram_id,
        }

    from app.infra.database.repository.employee.dto import CreateEmployeeDTO

    if not organization:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: организация не создана")
        return

    if telegram_id:
        existing_employees = await employee_service.get_by_organization_id(
            organization.id
        )
        is_already_employee = any(
            emp.telegram_id == telegram_id and emp.deleted_at is None
            for emp in existing_employees
        )

        if not is_already_employee:
            # Check if user is in TGBOT_ADMIN_IDS - if yes, assign administrator role
            # Use employee_type_id=3 for administrators, 1 for regular employees
            is_admin = telegram_id in config.TGBOT_ADMIN_IDS
            employee_type_id = 3 if is_admin else 1
            
            employee_dto = CreateEmployeeDTO(
                organization_id=organization.id,
                employee_type_id=employee_type_id,
                full_name=first_name,
                telegram_id=telegram_id,
            )
            await employee_service.create(employee_dto)

    if telegram_id:
        loaded_organization = await organization_service.get_by_user_telegram_id(
            telegram_id
        )
        if loaded_organization:
            dialog_manager.middleware_data["organization"] = loaded_organization

    if (
        not dialog_manager.middleware_data.get("user_data", {}).get("telegram_id")
        and telegram_id
    ):
        dialog_manager.middleware_data["user_data"] = {
            "first_name": first_name,
            "username": username,
            "telegram_id": telegram_id,
        }

    await callback.answer(
        f"Организация '{organization.name}' успешно создана!",
    )
    
    # Check if this is the first organization creation
    # If user has only one organization (the one just created), it's the first creation
    is_first_creation = False
    if telegram_id:
        all_organizations = await organization_service.get_all_by_user_telegram_id(telegram_id)
        # If user has only one organization, it's the first creation
        is_first_creation = len(all_organizations) == 1
    
    if is_first_creation:
        # For first creation, suggest adding/inviting employees
        dialog_manager.dialog_data["is_first_creation"] = True
        dialog_manager.dialog_data["organization_id"] = organization.id
        await dialog_manager.switch_to(OrganizationDialog.manage_employees)
    else:
        # For subsequent creations, just close the dialog
        await dialog_manager.done()


async def process_name_input(
    message: Message, widget: MessageInput, dialog_manager: DialogManager
):
    """Process name input.

    Args:
        message: Message object.
        widget: MessageInput widget.
        dialog_manager: Dialog manager.
    """
    if not message.text:
        await message.answer(
            "Название организации не может быть пустым. Попробуйте еще раз."
        )
        return

    name = message.text.strip()
    if not name:
        await message.answer(
            "Название организации не может быть пустым. Попробуйте еще раз."
        )
        return

    dialog_manager.dialog_data["name"] = name

    # Если редактируем существующую организацию, возвращаемся в меню редактирования
    if dialog_manager.dialog_data.get("organization_id"):
        await dialog_manager.switch_to(OrganizationDialog.edit_menu)
    else:
        await dialog_manager.switch_to(OrganizationDialog.code_input)


async def process_code_input(
    message: Message, widget: MessageInput, dialog_manager: DialogManager
):
    """Process code input.

    Args:
        message: Message object.
        widget: MessageInput widget.
        dialog_manager: Dialog manager.
    """
    if not message.text:
        await message.answer(
            "Код организации не может быть пустым. Попробуйте еще раз."
        )
        return

    code = message.text.strip().upper()
    if not code:
        await message.answer(
            "Код организации не может быть пустым. Попробуйте еще раз."
        )
        return

    dialog_manager.dialog_data["code"] = code

    # Если редактируем существующую организацию, возвращаемся в меню редактирования
    if dialog_manager.dialog_data.get("organization_id"):
        await dialog_manager.switch_to(OrganizationDialog.edit_menu)
    else:
        await dialog_manager.switch_to(OrganizationDialog.address_input)


async def process_address_input(
    message: Message, widget: MessageInput, dialog_manager: DialogManager
):
    """Process address input.

    Args:
        message: Message object.
        widget: MessageInput widget.
        dialog_manager: Dialog manager.
    """
    address = message.text.strip() if message.text else None
    dialog_manager.dialog_data["address"] = address if address else None

    # Если редактируем существующую организацию, возвращаемся в меню редактирования
    if dialog_manager.dialog_data.get("organization_id"):
        await dialog_manager.switch_to(OrganizationDialog.edit_menu)
    else:
        await dialog_manager.switch_to(OrganizationDialog.phone_input)


async def process_phone_input(
    message: Message, widget: MessageInput, dialog_manager: DialogManager
):
    """Process phone input.

    Args:
        message: Message object.
        widget: MessageInput widget.
        dialog_manager: Dialog manager.
    """
    phone = message.text.strip() if message.text else None
    dialog_manager.dialog_data["phone"] = phone if phone else None

    # Если редактируем существующую организацию, возвращаемся в меню редактирования
    if dialog_manager.dialog_data.get("organization_id"):
        await dialog_manager.switch_to(OrganizationDialog.edit_menu)
    else:
        await dialog_manager.switch_to(OrganizationDialog.confirm)


logger = logging.getLogger(__name__)


async def on_continue_to_main_menu(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
):
    """Handle continue to main menu button click after first organization creation.
    
    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    from app.tgbot.dialogs.greeting.states import GreetingDialog
    
    # Clear the first creation flag
    dialog_manager.dialog_data.pop("is_first_creation", None)
    
    # Close organization dialog and go to main menu
    await dialog_manager.done()
    await dialog_manager.start(GreetingDialog.greeting)


@inject
async def on_invite_employee(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    invitation_service: InvitationService = Provide[Container.invitation_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Handle invite employee button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        invitation_service: Invitation service instance (injected).
        employee_service: Employee service instance (injected).
    """
    
    # Check administrator access
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        from aiogram.types import Message as MessageType
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "❌ У вас нет прав доступа для приглашения сотрудников. "
                "Только администраторы могут приглашать сотрудников."
            )
        return
    
    # Get current organization
    organization = dialog_manager.middleware_data.get("organization")
    
    # If not in middleware_data, try to get from dialog_data or load by user
    if not organization:
        organization_id = dialog_manager.dialog_data.get("organization_id")
        if organization_id:
            organization = await organization_service.get_by_id(organization_id)
            if organization:
                dialog_manager.middleware_data["organization"] = organization
        
        # If still not found, try to get by user telegram_id
        if not organization:
            user_data = dialog_manager.middleware_data.get("user_data", {})
            telegram_id = user_data.get("telegram_id")
            if not telegram_id and callback.from_user:
                telegram_id = callback.from_user.id
            
            if telegram_id:
                organization = await organization_service.get_by_user_telegram_id(telegram_id)
                if organization:
                    dialog_manager.middleware_data["organization"] = organization
                    dialog_manager.dialog_data["organization_id"] = organization.id
    
    if not organization:
        from aiogram.types import Message as MessageType
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("❌ Ошибка: организация не выбрана")
        return
    
    # Get inviter telegram_id
    user_data = dialog_manager.middleware_data.get("user_data", {})
    inviter_telegram_id = user_data.get("telegram_id")
    if not inviter_telegram_id and callback.from_user:
        inviter_telegram_id = callback.from_user.id
    
    if not inviter_telegram_id:
        from aiogram.types import Message as MessageType
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("❌ Ошибка: не удалось определить пользователя")
        return
    
    # Create invitation code
    try:
        code = await invitation_service.create_invitation(
            inviter_telegram_id=inviter_telegram_id,
            organization_id=organization.id,
        )
        
        # Get bot username for link
        bot = dialog_manager.event.bot
        if not bot:
            from aiogram.types import Message as MessageType
            if callback.message and isinstance(callback.message, MessageType):
                msg: MessageType = callback.message
                await msg.answer("❌ Ошибка: не удалось получить информацию о боте")
            return
        
        assert bot is not None  # Type narrowing for linter
        bot_info = await bot.get_me()
        bot_username = bot_info.username
        
        invitation_link = f"https://t.me/{bot_username}?start={code}"
        
        # Store in dialog data
        dialog_manager.dialog_data["invitation_code"] = code
        dialog_manager.dialog_data["invitation_link"] = invitation_link
        
        await dialog_manager.switch_to(OrganizationDialog.invite_employee)
    except Exception as e:
        logger.error(f"Error creating invitation: {e}", exc_info=True)
        from aiogram.types import Message as MessageType
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                f"❌ Ошибка при создании приглашения: {str(e)}"
            )


