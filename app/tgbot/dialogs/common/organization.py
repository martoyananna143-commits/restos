"""Common organization selection components for reuse across dialogs."""

from typing import Any, Callable, Optional

from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager, Window
from aiogram_dialog.widgets.kbd import Back, Button, Cancel, Row, ScrollingGroup, Select, SwitchTo
from aiogram_dialog.widgets.text import Const, Format
from dependency_injector.wiring import Provide, inject

from app.internal import Container
from app.internal.usecases.organization_service import OrganizationService


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
    # Получаем telegram_id из события
    telegram_id = None
    if dialog_manager.event:
        from_user = getattr(dialog_manager.event, "from_user", None)
        if from_user:
            telegram_id = from_user.id

    organizations = []
    if telegram_id:
        organizations = await organization_service.get_all_by_user_telegram_id(
            telegram_id
        )

    has_organizations = len(organizations) > 0

    return {
        "organizations": organizations,
        "has_organizations": has_organizations,
        "organizations_count": len(organizations),
        "no_organizations": not has_organizations,
    }


# Глобальный словарь для хранения конфигурации handlers
_organization_handlers_config: dict[str, dict] = {}


def create_organization_select_handler(
    next_state,
    on_error_message: Optional[str] = None,
    on_success_callback: Optional[Callable] = None,
):
    """Create organization selection handler.

    Args:
        next_state: State to switch to after organization selection.
        on_error_message: Optional error message to show if organization not found.
        on_success_callback: Optional callback function called after successful selection.
            Receives (organization, dialog_manager) as arguments.

    Returns:
        Handler function.
    """
    handler_id = f"org_select_{id(next_state)}_{id(on_success_callback) if on_success_callback else 0}"

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
    """Internal handler for organization selection.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected organization ID.
        handler_id: Handler configuration ID.
        organization_service: Organization service instance (injected).
    """
    organization_id = int(item_id)

    config = _organization_handlers_config.get(handler_id, {})
    next_state = config.get("next_state")
    on_error_message = config.get("on_error_message")
    on_success_callback = config.get("on_success_callback")

    organization = await organization_service.get_by_id(organization_id)
    if organization:
        dialog_manager.dialog_data["organization_id"] = organization_id
        if on_success_callback:
            await on_success_callback(organization, dialog_manager)
        if next_state:
            await dialog_manager.switch_to(next_state)
    else:
        error_msg = on_error_message or "Ошибка: организация не найдена"
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(error_msg)


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

    Args:
        state: Dialog state for this window.
        message_text: Text to display above the organization list.
        next_state: State to switch to after organization selection.
        cancel_handler: Optional handler for cancel button.
        create_organization_handler: Optional handler for create organization button.
        use_scrolling: Whether to use ScrollingGroup for pagination (default: True).

    Returns:
        Window: The configured organization selection window.
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
                    text=Const("Создать новую организацию ➕"),
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

    return Window(
        *widgets,
        state=state,
        getter=get_organizations_list_data,
    )


@inject
async def on_select_organization(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Default organization selection handler (for backward compatibility).

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected organization ID.
        organization_service: Organization service instance (injected).
    """
    organization_id = int(item_id)

    organization = await organization_service.get_by_id(organization_id)
    if organization:
        dialog_manager.dialog_data["organization_id"] = organization_id
    else:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: организация не найдена")
