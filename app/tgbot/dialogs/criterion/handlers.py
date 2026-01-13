"""Handlers for criterion dialog."""

from typing import Optional

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, StartMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button
from dependency_injector.wiring import Provide, inject

from app.internal import Container
from app.internal.usecases.criterion_service import CriterionService
from app.internal.usecases.organization_service import OrganizationService
from app.tgbot.dialogs.common.evaluation_type import (
    confirm_evaluation_type,
)
from app.tgbot.dialogs.common.evaluation_type import (
    process_evaluation_type_code_input as common_process_code,
)
from app.tgbot.dialogs.common.evaluation_type import (
    process_evaluation_type_description_input as common_process_description,
)
from app.tgbot.dialogs.common.evaluation_type import (
    process_evaluation_type_name_input as common_process_name,
)
from app.tgbot.dialogs.common.evaluation_type import (
    skip_evaluation_type_description as common_skip_description,
)
from app.tgbot.dialogs.criterion.states import CriterionDialog
from app.tgbot.dialogs.greeting.states import GreetingDialog
from app.tgbot.dialogs.organization.states import OrganizationDialog


async def on_edit_value_type(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle edit value type button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.switch_to(CriterionDialog.select_value_type)


async def _handle_value_type_selection(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    value_type: str,
):
    """Internal handler for value type selection.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        value_type: Selected value type ('boolean', 'string', 'number').
    """

    dialog_manager.dialog_data["value_type"] = value_type

    if dialog_manager.dialog_data.get("criterion_id"):
        await dialog_manager.switch_to(CriterionDialog.edit_menu)
    else:
        await dialog_manager.switch_to(CriterionDialog.select_evaluation_type)


async def on_select_value_type(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: Optional[str] = None,
):
    """Handle value type selection (for Select widget).

    Args:
        callback: Callback query.
        widget: Widget instance (Select).
        dialog_manager: Dialog manager.
        item_id: Selected value type ('boolean', 'string', 'number').
    """
    await _handle_value_type_selection(callback, widget, dialog_manager, item_id)


async def on_select_value_type_boolean(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
):
    """Handle boolean value type selection.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await _handle_value_type_selection(callback, button, dialog_manager, "boolean")


async def on_select_value_type_string(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
):
    """Handle string value type selection.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await _handle_value_type_selection(callback, button, dialog_manager, "string")


async def on_select_value_type_number(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
):
    """Handle number value type selection.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await _handle_value_type_selection(callback, button, dialog_manager, "number")


async def on_create_organization_from_criterion(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle create organization button click from criterion dialog.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.start(
        OrganizationDialog.name_input,
        mode=StartMode.RESET_STACK,
    )


async def on_select_evaluation_type(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
):
    """Handle evaluation type selection.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected evaluation type ID.
    """
    evaluation_type_id = int(item_id)

    dialog_manager.dialog_data["evaluation_type_id"] = evaluation_type_id

    # Если редактируем существующий критерий, возвращаемся в меню редактирования
    if dialog_manager.dialog_data.get("criterion_id"):
        await dialog_manager.switch_to(CriterionDialog.edit_menu)
    else:
        await dialog_manager.switch_to(CriterionDialog.select_value_type)


# Wrapper handlers for evaluation type creation using common functions
async def process_evaluation_type_name_input(
    message: Message, widget: MessageInput, dialog_manager: DialogManager
):
    """Process evaluation type name input.

    Args:
        message: Message object.
        widget: MessageInput widget.
        dialog_manager: Dialog manager.
    """
    await common_process_name(
        message, widget, dialog_manager, CriterionDialog.evaluation_type_code_input
    )


async def process_evaluation_type_code_input(
    message: Message, widget: MessageInput, dialog_manager: DialogManager
):
    """Process evaluation type code input.

    Args:
        message: Message object.
        widget: MessageInput widget.
        dialog_manager: Dialog manager.
    """
    await common_process_code(
        message,
        widget,
        dialog_manager,
        CriterionDialog.evaluation_type_description_input,
    )


async def process_evaluation_type_description_input(
    message: Message, widget: MessageInput, dialog_manager: DialogManager
):
    """Process evaluation type description input.

    Args:
        message: Message object.
        widget: MessageInput widget.
        dialog_manager: Dialog manager.
    """
    await common_process_description(
        message, widget, dialog_manager, CriterionDialog.evaluation_type_confirm
    )


async def on_skip_evaluation_type_description(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle skip evaluation type description button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await common_skip_description(
        callback, button, dialog_manager, CriterionDialog.evaluation_type_confirm
    )


async def on_confirm_evaluation_type(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
):
    """Handle confirm evaluation type button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await confirm_evaluation_type(
        callback, button, dialog_manager, CriterionDialog.select_evaluation_type
    )


async def on_skip_description(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle skip description button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    dialog_manager.dialog_data["description"] = None

    # Если редактируем существующий критерий, возвращаемся в меню редактирования
    if dialog_manager.dialog_data.get("criterion_id"):
        await dialog_manager.switch_to(CriterionDialog.edit_menu)
    else:
        await dialog_manager.switch_to(CriterionDialog.confirm)


async def on_cancel_criterion(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle cancel button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await callback.answer("Создание критерия отменено")

    await dialog_manager.done()


@inject
async def on_confirm_criterion(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    organization_service: OrganizationService = Provide[Container.organization_service],
    criterion_service: CriterionService = Provide[Container.criterion_service],
):
    """Handle confirm criterion button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        organization_service: Organization service instance (injected).
        criterion_service: Criterion service instance (injected).
    """
    data = dialog_manager.dialog_data

    # Получаем organization_id из dialog_data
    organization_id = data.get("organization_id")
    if not organization_id:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: организация не найдена")
        await dialog_manager.start(
            GreetingDialog.greeting,
            mode=StartMode.RESET_STACK,
        )
        return

    # Проверяем, что организация существует
    organization = await organization_service.get_by_id(organization_id)
    if not organization:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: организация не найдена")
        await dialog_manager.start(
            GreetingDialog.greeting,
            mode=StartMode.RESET_STACK,
        )
        return

    # Получаем evaluation_type_id из dialog_data
    evaluation_type_id = data.get("evaluation_type_id")
    if not evaluation_type_id:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: тип оценки не выбран")
        await dialog_manager.start(
            GreetingDialog.greeting,
            mode=StartMode.RESET_STACK,
        )
        return

    # Проверяем наличие обязательных полей
    name: str = data.get("name", "")
    code: str = data.get("code", "")

    if not name or not code:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: название и код критерия обязательны")
        await dialog_manager.start(
            GreetingDialog.greeting,
            mode=StartMode.RESET_STACK,
        )
        return

    # Создаем критерий
    from app.infra.database.repository.criterion.dto import CreateCriterionDTO

    # Получаем value_type из dialog_data (по умолчанию 'boolean' для обратной совместимости)
    value_type = data.get("value_type", "boolean")

    criterion_dto = CreateCriterionDTO(
        organization_id=organization_id,
        evaluation_type_id=evaluation_type_id,
        name=name,
        code=code,
        description=data.get("description"),
        value_type=value_type,
    )

    criterion_id = data.get("criterion_id")

    try:
        if criterion_id:
            # Обновляем существующий критерий
            from app.infra.database.repository.criterion.dto import UpdateCriterionDTO

            # Получаем value_type из dialog_data (если не указан, не обновляем)
            value_type = data.get("value_type")

            update_dto = UpdateCriterionDTO(
                name=name,
                code=code,
                description=data.get("description"),
                evaluation_type_id=evaluation_type_id,
                value_type=value_type,
            )
            criterion = await criterion_service.update(criterion_id, update_dto)
            if criterion:
                await callback.answer(
                    f"Критерий '{criterion.name}' успешно обновлен!",
                )
            else:
                from aiogram.types import Message as MessageType

                if callback.message and isinstance(callback.message, MessageType):
                    await callback.message.answer(
                        "Ошибка: не удалось обновить критерий"
                    )
                return
        else:
            # Создаем новый критерий
            criterion = await criterion_service.create(criterion_dto)
            criterion_name = criterion.name

            await callback.answer(
                f"Критерий '{criterion_name}' успешно создан!",
            )
    except Exception as e:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(f"Ошибка при сохранении критерия: {str(e)}")
        return

    # Проверяем, пришли ли мы из создания набора критериев
    from_criterion_set = dialog_manager.middleware_data.get("from_criterion_set", False)
    if from_criterion_set:
        # Возвращаемся в выбор критериев для набора
        from app.tgbot.dialogs.criterion_set.states import CriterionSetDialog
        
        # Восстанавливаем состояние создания набора критериев
        criterion_set_state = dialog_manager.middleware_data.get("criterion_set_state", {})
        if criterion_set_state:
            dialog_manager.dialog_data["organization_id"] = criterion_set_state.get("organization_id")
            dialog_manager.dialog_data["name"] = criterion_set_state.get("name")
            dialog_manager.dialog_data["description"] = criterion_set_state.get("description")
            dialog_manager.dialog_data["selected_criterion_ids"] = criterion_set_state.get("selected_criterion_ids", [])
            dialog_manager.dialog_data["is_default"] = criterion_set_state.get("is_default", False)
            if criterion_set_state.get("criterion_set_id"):
                dialog_manager.dialog_data["criterion_set_id"] = criterion_set_state.get("criterion_set_id")
        
        # Добавляем созданный критерий в выбранные (если он был создан)
        if criterion and not criterion_id:  # Новый критерий
            selected_ids = dialog_manager.dialog_data.get("selected_criterion_ids", [])
            if criterion.id not in selected_ids:
                selected_ids.append(criterion.id)
                dialog_manager.dialog_data["selected_criterion_ids"] = selected_ids
        
        # Очищаем флаг
        dialog_manager.middleware_data.pop("from_criterion_set", None)
        dialog_manager.middleware_data.pop("criterion_set_state", None)
        
        # Переходим к выбору критериев для набора
        await dialog_manager.start(
            CriterionSetDialog.select_criteria,
            mode=StartMode.NORMAL,
        )
    elif criterion_id:
        # После редактирования возвращаемся в главное меню
        await dialog_manager.start(
            GreetingDialog.greeting,
            mode=StartMode.RESET_STACK,
        )
    else:
        await dialog_manager.switch_to(CriterionDialog.add_more)


async def on_add_more_no(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle add more no button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    # Проверяем, пришли ли мы из создания набора критериев
    from_criterion_set = dialog_manager.middleware_data.get("from_criterion_set", False)
    if from_criterion_set:
        # Возвращаемся в выбор критериев для набора
        from app.tgbot.dialogs.criterion_set.states import CriterionSetDialog
        
        # Восстанавливаем состояние создания набора критериев
        criterion_set_state = dialog_manager.middleware_data.get("criterion_set_state", {})
        if criterion_set_state:
            dialog_manager.dialog_data["organization_id"] = criterion_set_state.get("organization_id")
            dialog_manager.dialog_data["name"] = criterion_set_state.get("name")
            dialog_manager.dialog_data["description"] = criterion_set_state.get("description")
            dialog_manager.dialog_data["selected_criterion_ids"] = criterion_set_state.get("selected_criterion_ids", [])
            dialog_manager.dialog_data["is_default"] = criterion_set_state.get("is_default", False)
            if criterion_set_state.get("criterion_set_id"):
                dialog_manager.dialog_data["criterion_set_id"] = criterion_set_state.get("criterion_set_id")
        
        # Добавляем созданный критерий в выбранные (если он был создан)
        criterion_id = dialog_manager.dialog_data.get("criterion_id")
        if not criterion_id:  # Новый критерий был создан
            # Получаем последний созданный критерий из dialog_data
            # (он должен быть сохранен в on_confirm_criterion)
            pass  # Критерий уже добавлен в on_confirm_criterion
        
        # Очищаем флаг
        dialog_manager.middleware_data.pop("from_criterion_set", None)
        dialog_manager.middleware_data.pop("criterion_set_state", None)
        
        # Переходим к выбору критериев для набора
        await dialog_manager.start(
            CriterionSetDialog.select_criteria,
            mode=StartMode.NORMAL,
        )
    else:
        await dialog_manager.start(
            GreetingDialog.greeting,
            mode=StartMode.RESET_STACK,
        )


async def on_add_more_yes(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle add more yes button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    # Clear previous criterion data
    dialog_manager.dialog_data.pop("name", None)
    dialog_manager.dialog_data.pop("code", None)
    dialog_manager.dialog_data.pop("description", None)

    await dialog_manager.switch_to(
        CriterionDialog.name_input,
    )


async def on_add_more_no(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle add more no button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """

    await dialog_manager.start(
        GreetingDialog.greeting,
        mode=StartMode.RESET_STACK,
    )


# Edit menu handlers
@inject
async def on_select_existing_criterion(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
    criterion_service: CriterionService = Provide[Container.criterion_service],
):
    """Handle existing criterion selection.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected criterion ID.
        criterion_service: Criterion service instance (injected).
    """
    criterion_id = int(item_id)

    criterion = await criterion_service.get_by_id(criterion_id)
    if criterion:
        dialog_manager.dialog_data["criterion_id"] = criterion_id
        dialog_manager.dialog_data["name"] = criterion.name
        dialog_manager.dialog_data["code"] = criterion.code
        dialog_manager.dialog_data["description"] = criterion.description
        dialog_manager.dialog_data["evaluation_type_id"] = criterion.evaluation_type_id
        dialog_manager.dialog_data["value_type"] = getattr(
            criterion, "value_type", "boolean"
        )
        await dialog_manager.switch_to(CriterionDialog.edit_menu)
    else:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: критерий не найден")


async def on_create_new_criterion(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle create new criterion button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    # Очищаем данные предыдущего критерия
    dialog_manager.dialog_data.pop("criterion_id", None)
    dialog_manager.dialog_data.pop("name", None)
    dialog_manager.dialog_data.pop("code", None)
    dialog_manager.dialog_data.pop("description", None)
    dialog_manager.dialog_data.pop("value_type", None)
    # Сначала выбираем тип данных для критерия
    await dialog_manager.switch_to(CriterionDialog.select_value_type)


async def on_edit_name(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle edit name button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.switch_to(CriterionDialog.name_input)


async def on_edit_code(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle edit code button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.switch_to(CriterionDialog.code_input)


async def on_edit_description(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle edit description button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.switch_to(CriterionDialog.description_input)


async def on_edit_evaluation_type(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle edit evaluation type button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.switch_to(CriterionDialog.edit_evaluation_type)


async def on_save_changes(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle save changes button click - goes to confirm window.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.switch_to(CriterionDialog.confirm)


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
            "Название критерия не может быть пустым. Попробуйте еще раз."
        )
        return

    name = message.text.strip()
    if not name:
        await message.answer(
            "Название критерия не может быть пустым. Попробуйте еще раз."
        )
        return

    dialog_manager.dialog_data["name"] = name

    # Если редактируем существующий критерий, возвращаемся в меню редактирования
    if dialog_manager.dialog_data.get("criterion_id"):
        await dialog_manager.switch_to(CriterionDialog.edit_menu)
    else:
        await dialog_manager.switch_to(CriterionDialog.code_input)


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
        await message.answer("Код критерия не может быть пустым. Попробуйте еще раз.")
        return

    code = message.text.strip().upper()
    if not code:
        await message.answer("Код критерия не может быть пустым. Попробуйте еще раз.")
        return

    dialog_manager.dialog_data["code"] = code

    # Если редактируем существующий критерий, возвращаемся в меню редактирования
    if dialog_manager.dialog_data.get("criterion_id"):
        await dialog_manager.switch_to(CriterionDialog.edit_menu)
    else:
        await dialog_manager.switch_to(CriterionDialog.description_input)


async def process_description_input(
    message: Message, widget: MessageInput, dialog_manager: DialogManager
):
    """Process description input.

    Args:
        message: Message object.
        widget: MessageInput widget.
        dialog_manager: Dialog manager.
    """
    description = message.text.strip() if message.text else None
    dialog_manager.dialog_data["description"] = description if description else None

    # Если редактируем существующий критерий, возвращаемся в меню редактирования
    if dialog_manager.dialog_data.get("criterion_id"):
        await dialog_manager.switch_to(CriterionDialog.edit_menu)
    else:
        await dialog_manager.switch_to(CriterionDialog.confirm)
