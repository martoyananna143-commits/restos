"""Common criterion set selection components for reuse across dialogs."""

from typing import Any, Callable, Optional

from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager, Window
from aiogram_dialog.widgets.kbd import Back, Button, Cancel, Row, ScrollingGroup, Select, SwitchTo
from aiogram_dialog.widgets.text import Const, Format
from dependency_injector.wiring import Provide, inject

from app.internal import Container
from app.internal.usecases.criterion_set_service import CriterionSetService


@inject
async def get_criterion_sets_list_data(
    dialog_manager: DialogManager,
    criterion_set_service: CriterionSetService = Provide[Container.criterion_set_service],
    *args,
    **kwargs,
):
    """Get data for criterion sets list window.

    Args:
        dialog_manager: Dialog manager instance.
        criterion_set_service: CriterionSet service instance (injected).
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with criterion sets list data.
    """
    organization_id = dialog_manager.dialog_data.get("organization_id")
    # Если organization_id не найден в dialog_data, проверяем middleware_data
    if not organization_id:
        organization = dialog_manager.middleware_data.get("organization")
        if organization:
            organization_id = organization.id
            # Устанавливаем organization_id в dialog_data для последующих вызовов
            dialog_manager.dialog_data["organization_id"] = organization_id
        else:
            # Проверяем preset_organization_id в middleware_data
            preset_org_id = dialog_manager.middleware_data.get("preset_organization_id")
            if preset_org_id:
                organization_id = preset_org_id
                dialog_manager.dialog_data["organization_id"] = organization_id

    if not organization_id:
        return {
            "criterion_sets": [],
            "has_criterion_sets": False,
            "no_criterion_sets": True,
            "has_default_set": False,
        }

    criterion_sets = await criterion_set_service.get_by_organization_id(organization_id)

    # Проверяем наличие дефолтного набора
    default_set = next((cs for cs in criterion_sets if cs.is_default), None)

    # Для окна комбинирования наборов
    selected_set_ids = dialog_manager.dialog_data.get(
        "selected_set_ids_for_combine", []
    )
    selected_count = len(selected_set_ids)
    can_combine = selected_count >= 2

    criterion_sets_with_display = []
    for cs in criterion_sets:
        display_name = f"{cs.name} (Дефолтный)" if cs.is_default else cs.name
        # Добавляем маркер выбора для окна комбинирования
        selected_marker = "✅" if cs.id in selected_set_ids else "⬜"
        criterion_sets_with_display.append(
            {
                "id": cs.id,
                "name": cs.name,
                "description": cs.description,
                "is_default": cs.is_default,
                "display_name": display_name,
                "selected_marker": selected_marker,
            }
        )

    # Сохраняем default_set_id в dialog_data для использования в handlers
    if default_set:
        dialog_manager.dialog_data["default_set_id"] = default_set.id
    else:
        dialog_manager.dialog_data.pop("default_set_id", None)

    return {
        "criterion_sets": criterion_sets_with_display,
        "has_criterion_sets": len(criterion_sets) > 0,
        "no_criterion_sets": len(criterion_sets) == 0,
        "has_default_set": default_set is not None,
        "default_set_id": default_set.id if default_set else None,
        "selected_set_ids": selected_set_ids,
        "selected_count": selected_count,
        "can_combine": can_combine,
    }


def create_criterion_set_select_window(
    state,
    message_text: str,
    on_select_handler: Callable,
    on_use_default_handler: Optional[Callable] = None,
    on_combine_handler: Optional[Callable] = None,
    on_create_new_handler: Optional[Callable] = None,
    back_state: Optional[Any] = None,
    back_handler: Optional[Callable] = None,
    cancel_handler: Optional[Callable] = None,
    use_scrolling: bool = True,
    show_create_when_empty: bool = True,
    auto_create_when_empty: bool = False,
) -> Window:
    """Create criterion set selection window.

    Args:
        state: Dialog state for this window.
        message_text: Text to display above the criterion sets list.
        on_select_handler: Handler for criterion set selection.
        on_use_default_handler: Optional handler for using default set button.
        on_combine_handler: Optional handler for combining sets button.
        on_create_new_handler: Optional handler for create new set button.
        back_state: Optional state to go back to (uses SwitchTo).
        back_handler: Optional handler for back button (uses Button).
        cancel_handler: Optional handler for cancel button.
        use_scrolling: Whether to use ScrollingGroup for pagination (default: True).
        show_create_when_empty: Show create button when no sets exist (default: True).
        auto_create_when_empty: Auto-navigate to create when no sets exist (default: False).

    Returns:
        Window: The configured criterion set selection window.
    """
    widgets: list[Any] = [
        Format(message_text),
    ]

    # Кнопка использования дефолтного набора
    if on_use_default_handler:
        widgets.append(
            Row(
                Button(
                    text=Const("Использовать дефолтный набор ✅"),
                    id="use_default_set",
                    on_click=on_use_default_handler,
                    when="has_default_set",
                ),
            )
        )

    # Кнопка комбинирования наборов
    if on_combine_handler:
        widgets.append(
            Row(
                Button(
                    text=Const("Комбинировать наборы 🔗"),
                    id="combine_sets",
                    on_click=on_combine_handler,
                    when="has_criterion_sets",
                ),
            )
        )

    # Список наборов критериев
    select_widget: Any = Select(  # type: ignore[assignment]
        Format("{item[display_name]}"),
        item_id_getter=lambda cs: cs["id"] if isinstance(cs, dict) else cs.id,
        items="criterion_sets",
        id="select_criterion_set",
        on_click=on_select_handler,
        when="has_criterion_sets" if not use_scrolling else None,
    )

    if use_scrolling:
        final_select_widget: Any = ScrollingGroup(
            select_widget,
            id="scrolling_criterion_sets",
            width=1,
            height=10,
            when="has_criterion_sets",
        )
    else:
        final_select_widget = select_widget

    widgets.append(final_select_widget)

    # Кнопка создания нового набора
    if on_create_new_handler and show_create_when_empty:
        widgets.append(
            Row(
                Button(
                    text=Const("Создать новый набор ➕"),
                    id="create_new_set",
                    on_click=on_create_new_handler,
                    when="no_criterion_sets",
                ),
            )
        )

    # Кнопка "Назад" или "Отмена"
    if back_state:
        widgets.append(SwitchTo(Const("Назад"), id="back_criterion_set", state=back_state))
    elif back_handler:
        widgets.append(Button(Const("Назад"), id="back_criterion_set", on_click=back_handler))
    elif cancel_handler:
        widgets.append(Cancel(Const("Отмена")))
    else:
        widgets.append(Back(Const("Назад")))

    return Window(
        *widgets,
        state=state,
        getter=get_criterion_sets_list_data,
    )

