"""Common evaluation type selection and creation components for reuse across dialogs."""

from typing import Any, Callable, Optional

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import (
    Back,
    Button,
    Cancel,
    Group,
    Row,
    ScrollingGroup,
    Select,
    SwitchTo,
)
from aiogram_dialog.widgets.text import Const, Format
from dependency_injector.wiring import Provide, inject

from app.internal import Container
from app.internal.usecases.evaluation_type_service import EvaluationTypeService
from app.internal.usecases.organization_service import OrganizationService


@inject
async def get_evaluation_types_list_data(
    dialog_manager: DialogManager,
    evaluation_type_service: EvaluationTypeService = Provide[
        Container.evaluation_type_service
    ],
    organization_service: OrganizationService = Provide[Container.organization_service],
    *args,
    **kwargs,
):
    """Get data for evaluation types list window.
    
    Gets evaluation types from ALL organizations where user is a member.

    Args:
        dialog_manager: Dialog manager instance.
        evaluation_type_service: EvaluationType service instance (injected).
        organization_service: Organization service instance (injected).
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with evaluation types list data.
    """
    # Get all organizations where user is a member
    telegram_id = None
    if dialog_manager.event and hasattr(dialog_manager.event, "from_user") and dialog_manager.event.from_user:
        telegram_id = dialog_manager.event.from_user.id
    
    if not telegram_id:
        return {
            "evaluation_types": [],
            "has_evaluation_types": False,
            "evaluation_types_count": 0,
            "no_evaluation_types": True,
        }
    
    # Get all organizations where user is a member
    user_organizations = await organization_service.get_all_by_user_telegram_id(telegram_id)
    
    if not user_organizations:
        return {
            "evaluation_types": [],
            "has_evaluation_types": False,
            "evaluation_types_count": 0,
            "no_evaluation_types": True,
        }
    
    # Get evaluation types from all user's organizations
    all_evaluation_types = []
    organization_ids = []
    for org in user_organizations:
        organization_ids.append(org.id)
        org_evaluation_types = await evaluation_type_service.get_all(organization_id=org.id)
        all_evaluation_types.extend(org_evaluation_types)
    
    # Update dialog_data and middleware_data with first organization (for compatibility)
    if user_organizations:
        dialog_manager.dialog_data["organization_id"] = user_organizations[0].id
        dialog_manager.middleware_data["organization"] = user_organizations[0]
        dialog_manager.dialog_data["user_organization_ids"] = organization_ids

    evaluation_types = all_evaluation_types

    return {
        "evaluation_types": evaluation_types,
        "has_evaluation_types": len(evaluation_types) > 0,
        "evaluation_types_count": len(evaluation_types),
        "no_evaluation_types": len(evaluation_types) == 0,
    }


# Глобальный словарь для хранения конфигурации handlers
_evaluation_type_handlers_config: dict[str, dict] = {}


def create_evaluation_type_select_handler(
    next_state,
    on_error_message: Optional[str] = None,
    on_success_callback: Optional[Callable] = None,
):
    """Create evaluation type selection handler.

    Args:
        next_state: State to switch to after evaluation type selection.
        on_error_message: Optional error message to show if evaluation type not found.
        on_success_callback: Optional callback function called after successful selection.
            Receives (evaluation_type, dialog_manager) as arguments.

    Returns:
        Handler function.
    """
    handler_id = f"et_select_{id(next_state)}_{id(on_success_callback) if on_success_callback else 0}"

    _evaluation_type_handlers_config[handler_id] = {
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
        await _handle_evaluation_type_select(
            callback, widget, dialog_manager, item_id, handler_id
        )

    return handler


@inject
async def _handle_evaluation_type_select(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
    handler_id: str,
    evaluation_type_service: EvaluationTypeService = Provide[
        Container.evaluation_type_service
    ],
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Internal handler for evaluation type selection.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected evaluation type ID.
        handler_id: Handler configuration ID.
        evaluation_type_service: EvaluationType service instance (injected).
        organization_service: Organization service instance (injected).
    """
    evaluation_type_id = int(item_id)

    config = _evaluation_type_handlers_config.get(handler_id, {})
    next_state = config.get("next_state")
    on_error_message = config.get("on_error_message")
    on_success_callback = config.get("on_success_callback")

    evaluation_type = await evaluation_type_service.get_by_id(evaluation_type_id)
    if not evaluation_type:
        error_msg = on_error_message or "Ошибка: тип оценки не найден"
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(error_msg)
        return
    
    # Check if evaluation type belongs to user's organizations
    telegram_id = None
    if callback.from_user:
        telegram_id = callback.from_user.id
    
    user_organization_ids = dialog_manager.dialog_data.get("user_organization_ids")
    if not user_organization_ids and telegram_id:
        # Get all organizations where user is a member
        user_organizations = await organization_service.get_all_by_user_telegram_id(telegram_id)
        user_organization_ids = [org.id for org in user_organizations]
        dialog_manager.dialog_data["user_organization_ids"] = user_organization_ids
    
    # Check if evaluation type belongs to one of user's organizations
    if user_organization_ids and evaluation_type.organization_id:
        if evaluation_type.organization_id not in user_organization_ids:
            from aiogram.types import Message as MessageType
            error_msg = "Ошибка: выбранный тип оценки не принадлежит вашей организации."
            if callback.message and isinstance(callback.message, MessageType):
                await callback.message.answer(error_msg)
            return
    
    # Evaluation type is valid, proceed with selection
    dialog_manager.dialog_data["evaluation_type_id"] = evaluation_type_id
    if on_success_callback:
        result = await on_success_callback(evaluation_type, dialog_manager)
        # If callback returned True it already did its own switch_to — don't override.
        if result is True:
            return
    if next_state:
        await dialog_manager.switch_to(next_state)


def create_evaluation_type_select_window(
    state,
    message_text: str,
    next_state,
    cancel_handler: Optional[Callable] = None,
    create_evaluation_type_state: Optional[Any] = None,
    use_scrolling: bool = True,
    on_success_callback: Optional[Callable] = None,
    switch_to: Optional[SwitchTo] = None,
) -> Window:
    """Create evaluation type selection window.

    Args:
        state: Dialog state for this window.
        message_text: Text to display above the evaluation types list.
        next_state: State to switch to after evaluation type selection.
        cancel_handler: Optional handler for cancel/back button.
        create_evaluation_type_state: Optional state to switch to for creating new evaluation type.
        use_scrolling: Whether to use ScrollingGroup for pagination (default: True).
            For menu selection windows, set to False to disable pagination.
        on_success_callback: Optional callback function called after successful selection.

    Returns:
        Window: The configured evaluation type selection window.
    """
    select_handler = create_evaluation_type_select_handler(
        next_state, on_success_callback=on_success_callback
    )

    select_widget: Any = Select(  # type: ignore[assignment]
        Format("{item.name}"),
        item_id_getter=lambda et: et.id,
        items="evaluation_types",
        id="select_evaluation_type",
        on_click=select_handler,
        when="has_evaluation_types",
    )

    # For menu selection, don't use ScrollingGroup to avoid pagination
    # ScrollingGroup is only for lists of objects, not menu selections
    # Use Group with width=1 to display each button on a separate row
    if use_scrolling:
        final_select_widget: Any = ScrollingGroup(
            select_widget,
            id="scrolling_evaluation_types",
            width=1,
            height=10,
            when="has_evaluation_types",
            hide_on_single_page=True,
        )
    else:
        final_select_widget = Group(select_widget, width=1)

    widgets: list[Any] = [
        Format(message_text),
        final_select_widget,
    ]

    if create_evaluation_type_state:
        widgets.append(
            Row(
                SwitchTo(
                    text=Const("Создать новый тип оценки ➕"),
                    id="create_evaluation_type",
                    state=create_evaluation_type_state,
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
        getter=get_evaluation_types_list_data,
    )


def create_evaluation_type_name_input_window(
    state,
    process_name_handler: Callable,
    back_state: Optional[Any] = None,
) -> Window:
    """Create evaluation type name input window.

    Args:
        state: Dialog state for this window.
        process_name_handler: Handler for processing name input.
        back_state: Optional state to go back to (uses SwitchTo). If None, uses Back.

    Returns:
        Window: The configured evaluation type name input window.
    """
    widgets = [
        Const("Введите название типа оценки:"),
        MessageInput(process_name_handler),
    ]
    
    # Добавляем кнопку "Назад" с правильным переходом
    if back_state:
        widgets.append(SwitchTo(Const("Назад"), id="back_evaluation_type_name", state=back_state))
    else:
        widgets.append(Back(Const("Назад")))
    
    return Window(
        *widgets,  # type: ignore[arg-type]
        state=state,
    )


def create_evaluation_type_code_input_window(
    state,
    process_code_handler: Callable,
    back_state: Optional[Any] = None,
) -> Window:
    """Create evaluation type code input window.

    Args:
        state: Dialog state for this window.
        process_code_handler: Handler for processing code input.
        back_state: Optional state to go back to (uses SwitchTo). If None, uses Back.

    Returns:
        Window: The configured evaluation type code input window.
    """
    widgets = [
        Const("Введите код типа оценки (уникальный идентификатор):"),
        MessageInput(process_code_handler),
    ]
    
    # Добавляем кнопку "Назад" с правильным переходом
    if back_state:
        widgets.append(SwitchTo(Const("Назад"), id="back_evaluation_type_code", state=back_state))
    else:
        widgets.append(Back(Const("Назад")))
    
    return Window(
        *widgets,  # type: ignore[arg-type]
        state=state,
    )


def create_evaluation_type_description_input_window(
    state,
    process_description_handler: Callable,
    skip_handler: Callable,
    back_state: Optional[Any] = None,
) -> Window:
    """Create evaluation type description input window.

    Args:
        state: Dialog state for this window.
        process_description_handler: Handler for processing description input.
        skip_handler: Handler for skip button.
        back_state: Optional state to go back to (uses SwitchTo). If None, uses Back.

    Returns:
        Window: The configured evaluation type description input window.
    """
    from aiogram_dialog.widgets.kbd import SwitchTo
    
    widgets = [
        Const("Введите описание типа оценки (или нажмите 'Пропустить'):"),
        MessageInput(process_description_handler),
        Row(
            Button(
                text=Const("Пропустить ⏭️"),
                id="skip_evaluation_type_description",
                on_click=skip_handler,
            ),
        ),
    ]
    
    # Добавляем кнопку "Назад" с правильным переходом
    if back_state:
        widgets.append(SwitchTo(Const("Назад"), id="back_evaluation_type_description", state=back_state))
    else:
        widgets.append(Back(Const("Назад")))
    
    return Window(
        *widgets,  # type: ignore[arg-type]
        state=state,
    )


async def get_evaluation_type_form_data(
    dialog_manager: DialogManager,
    *args,
    **kwargs,
):
    """Get data for evaluation type form window.

    Args:
        dialog_manager: Dialog manager instance.
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with evaluation type form data.
    """
    data = dialog_manager.dialog_data
    description = data.get("evaluation_type_description")
    return {
        "name": data.get("evaluation_type_name", ""),
        "code": data.get("evaluation_type_code", ""),
        "description": description if description else "Не указано",
    }


def create_evaluation_type_confirm_window(
    state,
    confirm_handler: Callable,
    back_state: Optional[Any] = None,
) -> Window:
    """Create evaluation type confirm window.

    Args:
        state: Dialog state for this window.
        confirm_handler: Handler for confirm button.
        back_state: Optional state to go back to (uses SwitchTo). If None, uses Back.

    Returns:
        Window: The configured evaluation type confirm window.
    """
    widgets = [
        Format(
            "Проверьте данные типа оценки:\n\n"
            "Название: {name}\n"
            "Код: {code}\n"
            "Описание: {description}\n\n"
            "Всё верно?"
        ),
        Row(
            Button(
                text=Const("Подтвердить ✅"),
                id="confirm_evaluation_type",
                on_click=confirm_handler,
            ),
        ),
    ]
    
    # Добавляем кнопку "Назад" с правильным переходом
    if back_state:
        widgets.append(SwitchTo(Const("Назад"), id="back_evaluation_type_confirm", state=back_state))
    else:
        widgets.append(Back(Const("Назад")))
    
    return Window(
        *widgets,
        state=state,
        getter=get_evaluation_type_form_data,
    )


# Обработчики для создания типа оценки
async def process_evaluation_type_name_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    next_state,
):
    """Process evaluation type name input.

    Args:
        message: Message object.
        widget: MessageInput widget.
        dialog_manager: Dialog manager.
        next_state: State to switch to after processing.
    """
    if not message.text:
        await message.answer(
            "Название типа оценки не может быть пустым. Попробуйте еще раз."
        )
        return

    name = message.text.strip()
    if not name:
        await message.answer(
            "Название типа оценки не может быть пустым. Попробуйте еще раз."
        )
        return

    dialog_manager.dialog_data["evaluation_type_name"] = name
    await dialog_manager.switch_to(next_state)


async def process_evaluation_type_code_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    next_state,
):
    """Process evaluation type code input.

    Args:
        message: Message object.
        widget: MessageInput widget.
        dialog_manager: Dialog manager.
        next_state: State to switch to after processing.
    """
    if not message.text:
        await message.answer(
            "Код типа оценки не может быть пустым. Попробуйте еще раз."
        )
        return

    code = message.text.strip().upper()
    if not code:
        await message.answer(
            "Код типа оценки не может быть пустым. Попробуйте еще раз."
        )
        return

    dialog_manager.dialog_data["evaluation_type_code"] = code
    await dialog_manager.switch_to(next_state)


async def process_evaluation_type_description_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    next_state,
):
    """Process evaluation type description input.

    Args:
        message: Message object.
        widget: MessageInput widget.
        dialog_manager: Dialog manager.
        next_state: State to switch to after processing.
    """
    description = message.text.strip() if message.text else None
    dialog_manager.dialog_data["evaluation_type_description"] = (
        description if description else None
    )
    await dialog_manager.switch_to(next_state)


async def skip_evaluation_type_description(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    next_state,
):
    """Handle skip evaluation type description button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        next_state: State to switch to after skipping.
    """
    dialog_manager.dialog_data["evaluation_type_description"] = None
    await dialog_manager.switch_to(next_state)


@inject
async def confirm_evaluation_type(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    next_state,
    evaluation_type_service: EvaluationTypeService = Provide[
        Container.evaluation_type_service
    ],
    organization_service: OrganizationService = Provide[
        Container.organization_service
    ],
):
    """Handle confirm evaluation type button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        next_state: State to switch to after confirmation.
        evaluation_type_service: EvaluationType service instance (injected).
        organization_service: Organization service instance (injected).
    """
    data = dialog_manager.dialog_data

    name: str = data.get("evaluation_type_name", "")
    code: str = data.get("evaluation_type_code", "")
    organization_id = data.get("organization_id")

    if not name or not code:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "Ошибка: название и код типа оценки обязательны"
            )
        return

    # If organization_id is not set, try to get from user's organization
    if not organization_id:
        telegram_id = None
        if callback.from_user:
            telegram_id = callback.from_user.id
        
        if telegram_id:
            organization = await organization_service.get_by_user_telegram_id(telegram_id)
            if organization:
                organization_id = organization.id
                data["organization_id"] = organization_id

    if not organization_id:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "Ошибка: организация не выбрана. Сначала создайте или выберите организацию."
            )
        return

    # Создаем тип оценки
    from app.infra.database.repository.evaluation_type.dto import (
        CreateEvaluationTypeDTO,
    )

    evaluation_type_dto = CreateEvaluationTypeDTO(
        organization_id=organization_id,
        name=name,
        code=code,
        description=data.get("evaluation_type_description"),
    )

    try:
        evaluation_type = await evaluation_type_service.create(evaluation_type_dto)
        # Сохраняем созданный evaluation_type_id в dialog_data
        dialog_manager.dialog_data["evaluation_type_id"] = evaluation_type.id

        await callback.answer(
            f"Тип оценки '{evaluation_type.name}' успешно создан!",
        )
        # Переходим к следующему состоянию
        await dialog_manager.switch_to(next_state)
    except Exception as e:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(f"Ошибка при создании типа оценки: {str(e)}")




