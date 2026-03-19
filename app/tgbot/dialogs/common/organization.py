"""Common organization selection components for reuse across dialogs."""

import logging
from functools import partial
from typing import Any, Callable, Optional

from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager, Window
from aiogram_dialog.widgets.kbd import Back, Button, Cancel, Row, ScrollingGroup, Select, SwitchTo
from aiogram_dialog.widgets.text import Const, Format
from dependency_injector.wiring import Provide, inject

from app.internal import Container
from app.internal.usecases.organization_service import OrganizationService
from app.internal.usecases.user_service import UserService
from app.settings import config

logger = logging.getLogger(__name__)


def _is_superuser(telegram_id: int | None, dialog_manager: DialogManager) -> bool:
    """Quick in-session check for superuser status."""
    if telegram_id and telegram_id in config.TGBOT_ADMIN_IDS:
        return True
    user = dialog_manager.middleware_data.get("user")
    if user and getattr(user, "is_bot_administrator", False):
        return True
    # Also check cached flag set by get_greeting_data
    return bool(dialog_manager.middleware_data.get("is_superuser", False))


@inject
async def get_organizations_list_data(
    dialog_manager: DialogManager,
    organization_service: OrganizationService = Provide[Container.organization_service],
    *args,
    **kwargs,
):
    """Get data for organizations list window.

    Superusers see ALL organizations in the system.
    Non-superusers see only their own organizations.
    """
    telegram_id = None
    if dialog_manager.event:
        from_user = getattr(dialog_manager.event, "from_user", None)
        if from_user:
            telegram_id = from_user.id

    is_super = _is_superuser(telegram_id, dialog_manager)

    organizations = []
    if is_super:
        organizations = await organization_service.get_all()
    elif telegram_id:
        organizations = await organization_service.get_all_by_user_telegram_id(telegram_id)

    has_organizations = len(organizations) > 0

    return {
        "organizations": organizations,
        "has_organizations": has_organizations,
        "organizations_count": len(organizations),
        "no_organizations": not has_organizations,
        "auto_selected": False,
    }


@inject
async def auto_skip_getter(
    dialog_manager: DialogManager,
    organization_service: OrganizationService = Provide[Container.organization_service],
    user_service: UserService = Provide[Container.user_service],
    next_state=None,
    on_success_callback: Optional[Callable] = None,
    *args: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """Getter that can auto-select organization and skip the window.

    `next_state` и `on_success_callback` подставляются через `functools.partial`
    в фабрике окна, а сервисы приходят через DI (`Provide[...]`).
    """
    telegram_id = None
    if dialog_manager.event:
        from_user = getattr(dialog_manager.event, "from_user", None)
        if from_user:
            telegram_id = from_user.id
    if not telegram_id:
        user_data = dialog_manager.middleware_data.get("user_data", {})
        telegram_id = user_data.get("telegram_id")

    logger.info("[org getter] telegram_id=%s", telegram_id)

    # Суперюзер всегда видит список всех организаций — не скипаем.
    is_super = _is_superuser(telegram_id, dialog_manager)
    if is_super:
        logger.info("[org getter] superuser — show all orgs list")
        return await get_organizations_list_data(dialog_manager, *args, **kwargs)

    # Всегда берём активную организацию из БД (current_organization_id или первая по telegram_id).
    # get_by_telegram_id_any_chat — без привязки к chat_id, т.к. в другом апдейте/диалоге chat_id может не совпадать.
    organization = None
    if telegram_id:
        user = await user_service.repository.get_by_telegram_id_any_chat(telegram_id)  # type: ignore[union-attr]
        logger.info("[org getter] user_id=%s current_organization_id=%s", user.id if user else None, getattr(user, "current_organization_id", None) if user else None)
        if user:
            dialog_manager.middleware_data["user"] = user
            if getattr(user, "current_organization_id", None):
                organization = await organization_service.get_by_id(user.current_organization_id)
                logger.info("[org getter] org from current_organization_id: %s", organization.id if organization else None)
        if not organization:
            organization = await organization_service.get_by_user_telegram_id(telegram_id)
            logger.info("[org getter] org from get_by_user_telegram_id: %s", organization.id if organization else None)
        if organization:
            dialog_manager.middleware_data["organization"] = organization

    if organization:
        logger.info("[org getter] SKIP window, org_id=%s", organization.id)
        dialog_manager.dialog_data["organization_id"] = organization.id
        if on_success_callback:
            await on_success_callback(organization, dialog_manager)
        if next_state:
            await dialog_manager.switch_to(next_state)
        return {
            "organizations": [],
            "has_organizations": False,
            "organizations_count": 0,
            "no_organizations": True,
            "auto_selected": True,
        }

    logger.info("[org getter] SHOW list (no org), telegram_id=%s", telegram_id)
    return await get_organizations_list_data(dialog_manager, *args, **kwargs)


# --- Handler factory -------------------------------------------------------------

_organization_handlers_config: dict[str, dict] = {}


def create_organization_select_handler(
    next_state,
    on_error_message: Optional[str] = None,
    on_success_callback: Optional[Callable] = None,
):
    """Create organization selection handler."""
    handler_id = (
        f"org_select_{id(next_state)}_{id(on_success_callback) if on_success_callback else 0}"
    )

    _organization_handlers_config[handler_id] = {
        "next_state": next_state,
        "on_error_message": on_error_message,
        "on_success_callback": on_success_callback,
    }

    async def handler(
        callback: CallbackQuery,
        widget,
        dialog_manager: DialogManager,
        item_id: str,
    ):
        await _handle_organization_select(
            callback, widget, dialog_manager, item_id, handler_id
        )

    return handler


@inject
async def _handle_organization_select(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
    handler_id: str,
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Internal handler for organization selection."""
    organization_id = int(item_id)

    cfg = _organization_handlers_config.get(handler_id, {})
    next_state = cfg.get("next_state")
    on_error_message = cfg.get("on_error_message")
    on_success_callback = cfg.get("on_success_callback")

    organization = await organization_service.get_by_id(organization_id)
    if organization:
        dialog_manager.dialog_data["organization_id"] = organization_id
        dialog_manager.middleware_data["organization"] = organization
        if on_success_callback:
            await on_success_callback(organization, dialog_manager)
        if next_state:
            await dialog_manager.switch_to(next_state)
    else:
        error_msg = on_error_message or "Ошибка: организация не найдена"
        from aiogram.types import Message as MessageType
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(error_msg)


# --- Window factory --------------------------------------------------------------

def create_organization_select_window(
    state,
    message_text: str,
    next_state,
    cancel_handler: Optional[Callable] = None,
    create_organization_handler: Optional[Callable] = None,
    use_scrolling: bool = True,
    on_success_callback: Optional[Callable] = None,
    switch_to: Optional[SwitchTo] = None,
) -> Window:
    """Create organization selection window.

    Non-superusers whose organization is already known are automatically
    forwarded to next_state without seeing this window.
    """
    select_handler = create_organization_select_handler(
        next_state, on_success_callback=on_success_callback
    )

    select_widget: Any = Select(  # type: ignore[assignment]
        Format("{item.name}"),
        item_id_getter=lambda org: org.id,
        items="organizations",
        id="select_organization",
        on_click=select_handler,
        when="has_organizations" if not use_scrolling else None,
    )

    if use_scrolling:
        final_select_widget: Any = ScrollingGroup(
            select_widget,
            id="scrolling_organizations",
            width=1,
            height=10,
            when="has_organizations",
            hide_on_single_page=True,
        )
    else:
        final_select_widget = select_widget

    widgets: list[Any] = [
        Format(message_text),
        final_select_widget,
    ]

    if create_organization_handler:
        widgets.append(
            Row(
                Button(
                    text=Const("Создать новую организацию"),
                    id="create_organization",
                    on_click=create_organization_handler,
                    when="no_organizations",
                ),
            )
        )

    if cancel_handler:
        widgets.append(Cancel(Const("Отмена")))
    elif switch_to:
        widgets.append(switch_to)
    else:
        widgets.append(Back(Const("Назад")))

    # Use auto-skip getter; next_state и callback передаём через partial,
    # сам getter получает сервис через DI (Provide[...] в параметре).
    getter = partial(
        auto_skip_getter,
        next_state=next_state,
        on_success_callback=on_success_callback,
    )

    return Window(
        *widgets,
        state=state,
        getter=getter,
    )


@inject
async def on_select_organization(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Default organization selection handler (backward compatibility)."""
    organization_id = int(item_id)

    organization = await organization_service.get_by_id(organization_id)
    if organization:
        dialog_manager.dialog_data["organization_id"] = organization_id
        dialog_manager.middleware_data["organization"] = organization
    else:
        from aiogram.types import Message as MessageType
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: организация не найдена")
