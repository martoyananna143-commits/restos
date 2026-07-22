"""Handlers for employee dialog."""

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, StartMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button
from dependency_injector.wiring import Provide, inject

from app.infra.database.repository.employee.dto import (
    CreateEmployeeDTO,
    UpdateEmployeeDTO,
)
from app.internal import Container
from app.internal.services.employee_service import EmployeeService
from app.internal.services.organization_service import OrganizationService
from app.tgbot.dialogs.employee.states import EmployeeDialog
from app.tgbot.dialogs.greeting.states import GreetingDialog
from app.tgbot.dialogs.organization.states import OrganizationDialog


async def on_create_organization_from_employee(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle create organization button click from employee dialog.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.start(
        OrganizationDialog.name_input,
        mode=StartMode.RESET_STACK,
    )


@inject
async def on_select_employee_to_edit(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
    employee_service: EmployeeService = Provide[Container.employee_service],
):
    """Handle employee selection for editing.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected employee ID.
        employee_service: Employee service instance (injected).
    """
    employee_id = int(item_id)

    employee = await employee_service.get_by_id(employee_id)
    if employee:
        dialog_manager.dialog_data["employee_id"] = employee_id
        dialog_manager.dialog_data["organization_id"] = employee.organization_id
        dialog_manager.dialog_data["full_name"] = employee.full_name
        dialog_manager.dialog_data["position"] = employee.position
        dialog_manager.dialog_data["phone"] = employee.phone
        dialog_manager.dialog_data["employee_type_id"] = employee.employee_type_id
        type_name = next(
            (r["name"] for r in ROLE_MAP.values() if r["id"] == employee.employee_type_id),
            "Не назначена",
        )
        dialog_manager.dialog_data["employee_type_name"] = type_name
        await dialog_manager.switch_to(EmployeeDialog.edit_menu)
    else:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: сотрудник не найден")


# Edit menu handlers
async def on_edit_employee_full_name(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle edit full name button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.switch_to(EmployeeDialog.full_name_input)


async def on_edit_employee_position(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle edit position button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.switch_to(EmployeeDialog.position_input)


async def on_edit_employee_phone(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle edit phone button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.switch_to(EmployeeDialog.phone_input)


async def on_save_employee_changes(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle save changes button click - goes to confirm window.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.switch_to(EmployeeDialog.confirm)


async def on_skip_position(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle skip position button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    dialog_manager.dialog_data["position"] = None

    # Если редактируем существующего сотрудника, возвращаемся в меню редактирования
    if dialog_manager.dialog_data.get("employee_id"):
        await dialog_manager.switch_to(EmployeeDialog.edit_menu)
    else:
        await dialog_manager.switch_to(EmployeeDialog.phone_input)


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

    if dialog_manager.dialog_data.get("employee_id"):
        await dialog_manager.switch_to(EmployeeDialog.edit_menu)
    else:
        await dialog_manager.switch_to(EmployeeDialog.select_role)


async def on_cancel_employee(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle cancel button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await callback.answer("Создание сотрудника отменено")

    user_data = dialog_manager.middleware_data.get("user_data", {})
    if not user_data.get("telegram_id") and callback.from_user:
        dialog_manager.middleware_data["user_data"] = {
            "first_name": callback.from_user.first_name or "Пользователь",
            "username": callback.from_user.username or "",
            "telegram_id": callback.from_user.id,
        }

    await dialog_manager.done()


@inject
async def on_confirm_employee(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Handle confirm employee button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        employee_service: Employee service instance (injected).
        organization_service: Organization service instance (injected).
    """

    data = dialog_manager.dialog_data
    organization = dialog_manager.middleware_data.get("organization")

    if not organization:
        organization_id = data.get("organization_id")
        if organization_id:
            organization = await organization_service.get_by_id(organization_id)
            if organization:
                dialog_manager.middleware_data["organization"] = organization

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
                dialog_manager.dialog_data["organization_id"] = organization.id

    if not organization:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: организация не найдена")

        await dialog_manager.done()
        return

    employee_id = data.get("employee_id")

    if employee_id:
        update_dto = UpdateEmployeeDTO(
            full_name=data["full_name"],
            position=data.get("position"),
            phone=data.get("phone"),
            employee_type_id=data.get("employee_type_id"),
        )
        employee = await employee_service.update(employee_id, update_dto)
        if employee:
            await callback.answer(
                f"Сотрудник '{employee.full_name}' успешно обновлен!",
            )
            await dialog_manager.done()
            return
    else:
        employee_dto = CreateEmployeeDTO(
            organization_id=organization.id,
            employee_type_id=data.get("employee_type_id", 1),
            full_name=data["full_name"],
            position=data.get("position"),
            phone=data.get("phone"),
        )

        employee = await employee_service.create(employee_dto)

    if callback.message and hasattr(callback.message, "answer"):
        await callback.answer(f"Сотрудник '{employee.full_name}' успешно добавлен!")

    await dialog_manager.switch_to(EmployeeDialog.add_more)


async def on_add_more_yes(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle add more yes button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    # Clear previous employee data
    dialog_manager.dialog_data.pop("full_name", None)
    dialog_manager.dialog_data.pop("position", None)
    dialog_manager.dialog_data.pop("phone", None)
    await dialog_manager.switch_to(EmployeeDialog.full_name_input)


async def on_add_more_no(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle add more no button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """

    # Восстанавливаем user_data перед возвратом в главное меню
    user_data = dialog_manager.middleware_data.get("user_data", {})
    if not user_data.get("telegram_id") and callback.from_user:
        dialog_manager.middleware_data["user_data"] = {
            "first_name": callback.from_user.first_name or "Пользователь",
            "username": callback.from_user.username or "",
            "telegram_id": callback.from_user.id,
        }

    await dialog_manager.start(
        GreetingDialog.greeting,
        mode=StartMode.RESET_STACK,
    )


async def process_full_name_input(
    message: Message, widget: MessageInput, dialog_manager: DialogManager
):
    """Process full name input.

    Args:
        message: Message object.
        widget: MessageInput widget.
        dialog_manager: Dialog manager.
    """
    if not message.text:
        await message.answer("ФИО не может быть пустым. Попробуйте еще раз.")
        return

    full_name = message.text.strip()
    if not full_name:
        await message.answer("ФИО не может быть пустым. Попробуйте еще раз.")
        return

    dialog_manager.dialog_data["full_name"] = full_name

    # Если редактируем существующего сотрудника, возвращаемся в меню редактирования
    if dialog_manager.dialog_data.get("employee_id"):
        await dialog_manager.switch_to(EmployeeDialog.edit_menu)
    else:
        await dialog_manager.switch_to(EmployeeDialog.position_input)


async def process_position_input(
    message: Message, widget: MessageInput, dialog_manager: DialogManager
):
    """Process position input.

    Args:
        message: Message object.
        widget: MessageInput widget.
        dialog_manager: Dialog manager.
    """
    position = message.text.strip() if message.text else None
    dialog_manager.dialog_data["position"] = position if position else None

    # Если редактируем существующего сотрудника, возвращаемся в меню редактирования
    if dialog_manager.dialog_data.get("employee_id"):
        await dialog_manager.switch_to(EmployeeDialog.edit_menu)
    else:
        await dialog_manager.switch_to(EmployeeDialog.phone_input)


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

    if dialog_manager.dialog_data.get("employee_id"):
        await dialog_manager.switch_to(EmployeeDialog.edit_menu)
    else:
        await dialog_manager.switch_to(EmployeeDialog.select_role)


# =============================================================================
# Role (employee_type) management
# =============================================================================

ROLE_MAP = {
    "1": {"id": 1, "code": "employee", "name": "Сотрудник"},
    "2": {"id": 2, "code": "manager", "name": "Менеджер"},
    "3": {"id": 3, "code": "administrator", "name": "Администратор"},
}


async def on_edit_employee_role(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Switch to role selection screen."""
    await dialog_manager.switch_to(EmployeeDialog.select_role)


async def on_select_role(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
):
    """Handle role selection — save to dialog_data, return to edit_menu or confirm."""
    role = ROLE_MAP.get(item_id)
    if role:
        dialog_manager.dialog_data["employee_type_id"] = role["id"]
        dialog_manager.dialog_data["employee_type_name"] = role["name"]

    if dialog_manager.dialog_data.get("employee_id"):
        await dialog_manager.switch_to(EmployeeDialog.edit_menu)
    else:
        await dialog_manager.switch_to(EmployeeDialog.confirm)


async def get_roles_data(dialog_manager, *args, **kwargs):
    """Get available roles list for the select_role window."""
    current_type_id = dialog_manager.dialog_data.get("employee_type_id")
    roles = []
    for key, role in ROLE_MAP.items():
        marker = "✓ " if role["id"] == current_type_id else "◻ "
        roles.append({
            "id": key,
            "display": f"{marker}{role['name']}",
        })
    return {"roles": roles}
