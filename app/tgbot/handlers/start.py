import logging

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram_dialog import DialogManager, StartMode
from dependency_injector.wiring import Provide, inject

from app.infra.database.repository.employee.dto import CreateEmployeeDTO
from app.infra.database.repository.user.dto import TelegramUserDTO
from app.internal import Container
from app.internal.usecases.employee_service import EmployeeService
from app.internal.usecases.invitation_service import InvitationService
from app.internal.usecases.organization_service import OrganizationService
from app.internal.usecases.user_service import UserService
from app.settings import config
from app.tgbot.dialogs.greeting.states import GreetingDialog
from app.tgbot.dialogs.organization.states import OrganizationDialog
from app.tgbot.filters.admin import AdminFilter

start_router = Router()
logger = logging.getLogger(__name__)


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
                organization_id = invitation_data.get("organization_id")
                inviter_telegram_id = invitation_data.get("inviter_telegram_id")

                # Get or create user
                user = await user_service.sync_user_with_telegram(
                    telegram_user, chat_id
                )
                if not user:
                    user, created = await user_service.get_or_create_user(
                        telegram_user, chat_id
                    )
                    logger.info(f"Created new user from invitation: {user.telegram_id}")

                # Check if employee already exists
                existing_employee = (
                    await employee_service.get_by_telegram_id_and_organization_id(
                        user.telegram_id, organization_id
                    )
                )

                if not existing_employee:
                    # Create employee for invited user
                    # Check if user is in TGBOT_ADMIN_IDS - if yes, assign administrator role
                    # Use employee_type_id=3 for administrators, 1 for regular employees
                    is_admin = user.telegram_id in config.TGBOT_ADMIN_IDS
                    employee_type_id = 3 if is_admin else 1
                    
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
                        f"in organization {organization_id} via invitation"
                    )

                    await message.answer(
                        f"✅ Вы успешно присоединились к организации! "
                        f"Добро пожаловать, {user.first_name or 'Пользователь'}!"
                    )
                else:
                    logger.info(
                        f"User {user.telegram_id} already exists as employee "
                        f"in organization {organization_id}"
                    )
                    await message.answer(
                        f"✅ Вы уже являетесь сотрудником этой организации!"
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
    is_admin = user.telegram_id in config.TGBOT_ADMIN_IDS

    dialog_manager.middleware_data["user_data"] = {
        "first_name": user.first_name or "Пользователь",
        "username": user.username or "",
        "telegram_id": user.telegram_id,
    }
    dialog_manager.middleware_data["is_admin"] = is_admin

    organization = await organization_service.get_by_user_telegram_id(user.telegram_id)
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
