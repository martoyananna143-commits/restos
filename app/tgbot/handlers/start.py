import logging

from aiogram import Router, Bot, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, ErrorEvent
from aiogram_dialog import DialogManager, StartMode
from dependency_injector.wiring import Provide, inject

from app.infra.database.repository.employee.dto import CreateEmployeeDTO
from app.infra.database.repository.user.dto import TelegramUserDTO
from app.internal import Container
from app.internal.usecases.employee_service import EmployeeService
from app.internal.usecases.evaluation_service import EvaluationService
from app.internal.usecases.invitation_service import InvitationService
from app.internal.usecases.organization_service import OrganizationService
from app.internal.usecases.user_service import UserService
from app.settings import config
from app.tgbot.dialogs.greeting.states import GreetingDialog

start_router = Router()
logger = logging.getLogger(__name__)


async def _answer_if_message(callback: CallbackQuery, text: str) -> None:
    """Send text as a reply when callback has an accessible Message."""
    if callback.message and isinstance(callback.message, Message):
        await callback.message.answer(text)


@start_router.message(CommandStart(), flags={"rate_limit": {"rate": 5}})
@inject
async def start_handler(
    message: Message,
    dialog_manager: DialogManager,
    user_service: UserService = Provide[Container.user_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
    invitation_service: InvitationService = Provide[Container.invitation_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
):
    """
    Handles the /start command.

    Checks if user exists in database, syncs with Telegram data if needed,
    processes invitation codes if present, and starts greeting dialog.

    Args:
        message: The incoming message object.
        dialog_manager: The dialog manager instance.
        user_service: User service instance (injected).
        organization_service: Organization service instance (injected).
        invitation_service: Invitation service instance (injected).
        employee_service: Employee service instance (injected).

    Returns:
        None
    """
    if not message.from_user:
        return

    telegram_user = TelegramUserDTO(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        version=0,
    )

    chat_id = message.chat.id

    # Extract invitation code from /start command
    invitation_code = None
    if message.text and len(message.text.split()) > 1:
        invitation_code = message.text.split()[1].strip()

    # Process invitation code if present
    if invitation_code:
        try:
            invitation_data = await invitation_service.use_invitation(invitation_code)

            if invitation_data:
                invitation_type = invitation_data.get("invitation_type", "employee")
                organization_id = invitation_data.get("organization_id")
                _inviter_telegram_id = invitation_data.get("inviter_telegram_id")

                # Get or create user
                user = await user_service.sync_user_with_telegram(
                    telegram_user, chat_id
                )
                if not user:
                    user, created = await user_service.get_or_create_user(
                        telegram_user, chat_id
                    )
                    logger.info(f"Created new user from invitation: {user.telegram_id}")

                # Handle admin invitation
                if invitation_type == "admin":
                    if not user:
                        await message.answer("❌ Ошибка: не удалось найти пользователя")
                        return
                    
                    # Update user to set is_bot_administrator = True
                    from app.infra.database.repository.user.dto import UpdateUserDTO
                    update_dto = UpdateUserDTO(
                        telegram_id=user.telegram_id,
                        is_bot_administrator=True,
                    )
                    updated_user = await user_service.repository.update(user.id, update_dto)
                    
                    if not updated_user:
                        await message.answer("❌ Ошибка: не удалось обновить статус пользователя")
                        return
                    
                    user = updated_user
                    logger.info(
                        f"User {user.telegram_id} granted bot administrator status via invitation"
                    )
                    
                    await message.answer(
                        f"✅ Вы получили статус администратора! "
                        f"Теперь вы можете создать свою организацию. "
                        f"Добро пожаловать, {user.first_name or 'Пользователь'}!"
                    )
                else:
                    # Handle employee invitation (existing logic)
                    if not organization_id:
                        await message.answer(
                            "❌ Ошибка: код приглашения недействителен."
                        )
                        return
                    
                    # Check if employee already exists
                    existing_employee = (
                        await employee_service.get_by_telegram_id_and_organization_id(
                            user.telegram_id, organization_id
                        )
                    )

                    if not existing_employee:
                        is_admin = (
                            user.telegram_id in config.TGBOT_ADMIN_IDS
                            or (hasattr(user, 'is_bot_administrator') and user.is_bot_administrator)
                        )
                        invite_type_id = invitation_data.get("employee_type_id")
                        if is_admin:
                            employee_type_id = 3
                        elif invite_type_id:
                            employee_type_id = int(invite_type_id)
                        else:
                            employee_type_id = 1

                        employee_dto = CreateEmployeeDTO(
                            telegram_id=user.telegram_id,
                            organization_id=organization_id,
                            employee_type_id=employee_type_id,
                            full_name=user.first_name or "Пользователь",
                            username=user.username,
                            is_active=True,
                        )

                        employee = await employee_service.create(employee_dto)
                        logger.info(
                            f"Created employee {employee.id} for user {user.telegram_id} "
                            f"in organization {organization_id} via invitation "
                            f"(employee_type_id={employee_type_id})"
                        )

                        role_names = {1: "сотрудник", 2: "менеджер", 3: "администратор"}
                        role_label = role_names.get(employee_type_id, "сотрудник")
                        await message.answer(
                            f"✅ Вы успешно присоединились к организации как {role_label}! "
                            f"Добро пожаловать, {user.first_name or 'Пользователь'}!"
                        )
                    else:
                        logger.info(
                            f"User {user.telegram_id} already exists as employee "
                            f"in organization {organization_id}"
                        )
                        await message.answer(
                            "✅ Вы уже являетесь сотрудником этой организации!"
                        )
            else:
                await message.answer(
                    "❌ Код приглашения недействителен или уже использован. "
                    "Обратитесь к администратору для получения нового кода."
                )
                return
        except Exception as e:
            logger.error(f"Error processing invitation code: {e}", exc_info=True)
            await message.answer(
                "❌ Произошла ошибка при обработке кода приглашения. "
                "Попробуйте позже или обратитесь к администратору."
            )
            return

    # Get or create user (if not already done in invitation processing)
    user = await user_service.sync_user_with_telegram(telegram_user, chat_id)
    user_created = False
    if not user:
        user, user_created = await user_service.get_or_create_user(telegram_user, chat_id)
        logger.info(f"Created new user: {user.telegram_id}")

    # Сохраняем user_data и is_admin в middleware_data
    is_admin = (
        user.telegram_id in config.TGBOT_ADMIN_IDS 
        or (hasattr(user, 'is_bot_administrator') and user.is_bot_administrator)
    )

    dialog_manager.middleware_data["user_data"] = {
        "first_name": user.first_name or "Пользователь",
        "username": user.username or "",
        "telegram_id": user.telegram_id,
    }
    dialog_manager.middleware_data["user"] = user
    dialog_manager.middleware_data["is_admin"] = is_admin

    organization = None
    current_org_id = getattr(user, "current_organization_id", None)
    if current_org_id:
        organization = await organization_service.get_by_id(current_org_id)
    if not organization:
        organization = await organization_service.get_by_user_telegram_id(user.telegram_id)
        if organization and user:
            await user_service.repository.set_current_organization(user.id, organization.id)
            user.current_organization_id = organization.id
    dialog_manager.middleware_data["organization"] = organization

    if not organization:
        # For new users without organization, show help dialog first
        from app.tgbot.dialogs.help.states import HelpDialog
        await dialog_manager.start(
            HelpDialog.main_help,
            mode=StartMode.RESET_STACK,
        )
    else:
        await dialog_manager.start(
            GreetingDialog.greeting,
            mode=StartMode.RESET_STACK,
        )


async def on_unknown_intent(event, dialog_manager: DialogManager):
    """
    Handles unknown intents by restarting the dialog.

    Args:
        event: The event object containing the exception (ErrorEvent).
        dialog_manager (DialogManager): The dialog manager
        to control the dialog flow.

    Returns:
        None
    """

    logger.error("Restarting dialog: %s", event.exception)
    
    # Try to extract telegram_id from the original update in ErrorEvent
    telegram_id = None
    if hasattr(event, "update") and event.update:
        update = event.update
        # Try to get telegram_id from various update types
        if hasattr(update, "callback_query") and update.callback_query:
            if hasattr(update.callback_query, "from_user") and update.callback_query.from_user:
                telegram_id = update.callback_query.from_user.id
        elif hasattr(update, "message") and update.message:
            if hasattr(update.message, "from_user") and update.message.from_user:
                telegram_id = update.message.from_user.id
    
    # Store telegram_id in middleware_data if found
    if telegram_id:
        dialog_manager.middleware_data["user_data"] = {
            "telegram_id": telegram_id,
            "first_name": None,
            "username": None,
        }

    await dialog_manager.start(
        GreetingDialog.greeting,
        mode=StartMode.RESET_STACK,
    )


async def on_unknown_state(event, dialog_manager: DialogManager):
    """
    Handles unknown states by restarting the dialog.

    Args:
        event: The event object containing the exception.
        dialog_manager (DialogManager): The dialog manager
        to control the dialog flow.

    Returns:
        None
    """

    logger.error("Restarting dialog: %s", event.exception)

    await dialog_manager.start(
        GreetingDialog.greeting,
        mode=StartMode.RESET_STACK,
    )


async def on_unregistered_window(event, dialog_manager: DialogManager):
    """
    Handles unregistered windows by restarting the dialog.

    Args:
        event: The event object containing the exception.
        dialog_manager (DialogManager): The dialog manager
        to control the dialog flow.

    Returns:
        None
    """

    logger.error("Restarting dialog: %s", event.exception)

    await dialog_manager.start(
        GreetingDialog.greeting,
        mode=StartMode.RESET_STACK,
    )


async def on_network_error(event: ErrorEvent, bot: Bot):
    """Handle TelegramNetworkError by recreating the bot's HTTP session.

    When aiohttp hits a request timeout (e.g. uploading a large video),
    the underlying connection may become unusable.  Closing and
    re-opening the session restores connectivity.
    """
    logger.error(
        "TelegramNetworkError caught — recreating bot session: %s",
        event.exception,
    )
    try:
        await bot.session.close()
    except Exception as close_exc:
        logger.warning("Error closing old session: %s", close_exc)

    # aiogram lazily recreates the session on the next API call,
    # so we just need to reset it.
    from aiogram.client.session.aiohttp import AiohttpSession
    bot.session = AiohttpSession()
    logger.info("Bot session has been recreated successfully")


# ==================== Export Callbacks (from web form) ====================

@start_router.callback_query(F.data.startswith("export_dialog:"))
@inject
async def export_dialog_callback(
    callback: CallbackQuery,
    dialog_manager: DialogManager,
    evaluation_service: EvaluationService = Provide[Container.evaluation_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Handle export dialog callback - start export dialog."""
    from app.tgbot.dialogs.export.states import ExportDialog
    
    await callback.answer()
    
    try:
        if not callback.data or ":" not in callback.data:
            await _answer_if_message(callback, "❌ Неверные данные")
            return
        evaluation_id = int(callback.data.split(":")[1])
        
        # Get evaluation
        evaluation = await evaluation_service.get_by_id(evaluation_id)
        if not evaluation:
            await _answer_if_message(callback, "❌ Оценка не найдена")
            return
        
        # Get related data
        organization = await organization_service.get_by_id(evaluation.organization_id)
        evaluated_employee = await employee_service.get_by_id(evaluation.evaluated_employee_id) if evaluation.evaluated_employee_id else None
        filled_by_employee = await employee_service.get_by_id(evaluation.filled_by_employee_id) if evaluation.filled_by_employee_id else None
        
        # Start export dialog with evaluation data
        await dialog_manager.start(
            ExportDialog.select_format,
            mode=StartMode.RESET_STACK,
            data={
                "evaluation_id": evaluation_id,
                "organization_name": organization.name if organization else "Не указано",
                "evaluated_employee_name": evaluated_employee.full_name if evaluated_employee else "Не указано",
                "filled_by_employee_name": filled_by_employee.full_name if filled_by_employee else "Не указано",
                "total_criteria": evaluation.total_criteria or 0,
                "passed_criteria": evaluation.passed_criteria or 0,
                "failed_criteria": evaluation.failed_criteria or 0,
                "score_percentage": evaluation.score_percentage or 0.0,
                "evaluation_date": evaluation.evaluation_date.strftime("%d.%m.%Y %H:%M") if evaluation.evaluation_date else None,
            },
        )
        
    except Exception as e:
        logger.error(f"Error in export dialog callback: {e}", exc_info=True)
        await _answer_if_message(callback, f"❌ Ошибка: {str(e)}")


@start_router.callback_query(F.data == "back_to_greeting")
async def back_to_greeting_callback(
    callback: CallbackQuery,
    dialog_manager: DialogManager,
):
    """Handle back to greeting callback."""
    await callback.answer()
    await dialog_manager.start(
        GreetingDialog.greeting,
        mode=StartMode.RESET_STACK,
    )
