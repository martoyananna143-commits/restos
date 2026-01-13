"""Windows for greeting dialog."""

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


@inject
async def _check_administrator_access(
    callback: CallbackQuery,
    dialog_manager: DialogManager,
    employee_service: EmployeeService,
    organization_service: OrganizationService = Provide[Container.organization_service],
) -> bool:
    """Check if user has administrator access in current organization.

    First checks if user is in TGBOT_ADMIN_IDS from env (this takes precedence),
    then checks employee_type_code in organization.

    Args:
        callback: Callback query.
        dialog_manager: Dialog manager.
        employee_service: Employee service instance.
        organization_service: Organization service instance (injected).

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

    # Second check: check employee_type in organization
    # Get current organization from middleware_data or dialog_data
    organization = dialog_manager.middleware_data.get("organization")
    organization_id = None
    
    if organization:
        organization_id = organization.id
    else:
        organization_id = dialog_manager.dialog_data.get("organization_id")
        if not organization_id:
            # Try to get from organization service
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


@inject
async def on_edit_employee_clicked(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Handle edit employee button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        employee_service: Employee service instance (injected).
        organization_service: Organization service instance (injected).
    """
    
    # Check administrator access
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "❌ У вас нет прав доступа для управления сотрудниками. "
                "Только администраторы могут редактировать сотрудников."
            )
        return
    
    # Всегда переходим к выбору организации для редактирования сотрудника
    await dialog_manager.start(
        EmployeeDialog.select_organization_for_edit,
    )


async def on_start_work_clicked(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle start work button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await callback.answer("Начинаем работу!")

    # Сохраняем user_data при каждом действии для надежности
    if callback.from_user:
        dialog_manager.middleware_data["user_data"] = {
            "first_name": callback.from_user.first_name or "Пользователь",
            "username": callback.from_user.username or "",
            "telegram_id": callback.from_user.id,
        }

    # Here you can navigate to another dialog or perform actions


async def on_help_clicked(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle help button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    from app.tgbot.dialogs.help.states import HelpDialog


    # Сохраняем user_data при каждом действии для надежности
    if callback.from_user:
        dialog_manager.middleware_data["user_data"] = {
            "first_name": callback.from_user.first_name or "Пользователь",
            "username": callback.from_user.username or "",
            "telegram_id": callback.from_user.id,
        }

    # Start help dialog
    await dialog_manager.start(HelpDialog.main_help)


@inject
async def on_create_employee_clicked(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Handle create employee button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        employee_service: Employee service instance (injected).
        organization_service: Organization service instance (injected).
    """
    
    # Check administrator access
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "❌ У вас нет прав доступа для управления сотрудниками. "
                "Только администраторы могут создавать сотрудников."
            )
        return

    organization = dialog_manager.middleware_data.get("organization")

    if not organization:
        user_data = dialog_manager.middleware_data.get("user_data", {})
        telegram_id = user_data.get("telegram_id")

        # Если telegram_id нет в user_data, берем из callback
        if not telegram_id and callback.from_user:
            telegram_id = callback.from_user.id

        if telegram_id:
            organization = await organization_service.get_by_user_telegram_id(
                telegram_id
            )
            if organization:
                dialog_manager.middleware_data["organization"] = organization

    if not organization:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "Для создания сотрудника необходимо сначала создать организацию."
            )
        await dialog_manager.start(
            OrganizationDialog.check_organization,
            mode=StartMode.RESET_STACK,
        )
        return

    await dialog_manager.start(
        state=EmployeeDialog.select_organization,
    )


@inject
async def on_create_criterion_clicked(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Handle create criterion button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        employee_service: Employee service instance (injected).
        organization_service: Organization service instance (injected).
    """
    
    # Check administrator access
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "❌ У вас нет прав доступа для управления критериями. "
                "Только администраторы могут создавать критерии."
            )
        return

    telegram_id = None
    if callback.from_user:
        telegram_id = callback.from_user.id

    if telegram_id:
        organization = await organization_service.get_by_user_telegram_id(telegram_id)
        if not organization:
            if callback.message and isinstance(callback.message, MessageType):
                await callback.message.answer(
                    "Для создания критерия необходимо сначала создать организацию."
                )
            await dialog_manager.start(
                OrganizationDialog.check_organization,
                mode=StartMode.RESET_STACK,
            )
            return

    await dialog_manager.start(
        state=CriterionDialog.select_organization,
        mode=StartMode.NORMAL,
        show_mode=ShowMode.EDIT,
    )


@inject
async def on_create_criterion_set_clicked(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Handle create criterion set button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        employee_service: Employee service instance (injected).
        organization_service: Organization service instance (injected).
    """
    
    # Check administrator access
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "❌ У вас нет прав доступа для управления наборами критериев. "
                "Только администраторы могут управлять наборами критериев."
            )
        return

    telegram_id = None
    if callback.from_user:
        telegram_id = callback.from_user.id

    if telegram_id:
        organization = await organization_service.get_by_user_telegram_id(telegram_id)
        if not organization:
            from aiogram.types import Message as MessageType

            if callback.message and isinstance(callback.message, MessageType):
                await callback.message.answer(
                    "Для создания набора критериев необходимо сначала создать организацию."
                )
            await dialog_manager.start(
                OrganizationDialog.check_organization,
                mode=StartMode.RESET_STACK,
            )
            return

    await dialog_manager.start(
        state=CriterionSetDialog.select_organization,
    )


@inject
async def on_create_evaluation_clicked(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    organization_service: OrganizationService = Provide[Container.organization_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
):
    """Handle create evaluation button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        organization_service: Organization service instance (injected).
        employee_service: Employee service instance (injected).
    """

    telegram_id = None
    if callback.from_user:
        telegram_id = callback.from_user.id

    if telegram_id:
        organization = await organization_service.get_by_user_telegram_id(telegram_id)
        if not organization:
            from aiogram.types import Message as MessageType

            if callback.message and isinstance(callback.message, MessageType):
                await callback.message.answer(
                    "Для создания замера необходимо сначала создать организацию."
                )
            await dialog_manager.start(
                OrganizationDialog.check_organization,
                mode=StartMode.RESET_STACK,
            )
            return

        # Check if user is administrator
        is_administrator = False
        employee = await employee_service.get_by_telegram_id_and_organization_id(
            telegram_id, organization.id
        )
        if employee:
            employee_type_code = employee.meta.get("employee_type_code")
            is_administrator = employee_type_code == "administrator"

        # For non-administrators: automatically set organization and employee
        if not is_administrator:
            # Start evaluation dialog with pre-filled data
            await dialog_manager.start(
                state=EvaluationDialog.select_evaluation_type,
            )
            # Set organization and current employee automatically
            dialog_manager.dialog_data["organization_id"] = organization.id
            dialog_manager.middleware_data["organization"] = organization
            
            # Set current employee as filled_by_employee
            if employee:
                dialog_manager.dialog_data["filled_by_employee_id"] = employee.id
                dialog_manager.dialog_data["filled_by_employee_name"] = employee.full_name
        else:
            # For administrators: normal flow with organization selection
            await dialog_manager.start(
                state=EvaluationDialog.select_evaluation_type,
            )
    else:
        await dialog_manager.start(
            state=EvaluationDialog.select_evaluation_type,
        )
