"""Windows for evaluation dialog."""

from aiogram_dialog import Window
from aiogram_dialog.widgets.kbd import (
    Back,
    Button,
    Cancel,
    Row,
    ScrollingGroup,
    Select,
    SwitchTo,
)
from aiogram_dialog.widgets.text import Const, Format

from app.tgbot.dialogs.common.criterion_set import create_criterion_set_select_window
from app.tgbot.dialogs.common.evaluation_type import (
    create_evaluation_type_code_input_window,
    create_evaluation_type_confirm_window,
    create_evaluation_type_description_input_window,
    create_evaluation_type_name_input_window,
    create_evaluation_type_select_window,
)
from app.tgbot.dialogs.common.organization import create_organization_select_window
from app.tgbot.dialogs.evaluation.getters import (
    get_criterion_sets_list_data,
    get_employees_list_data,
    get_evaluations_list_data_for_deletion,
)
from app.tgbot.dialogs.evaluation.handlers import (
    _on_evaluation_type_selected,
    on_cancel_evaluation,
    on_combine_criterion_sets,
    on_confirm_evaluation_type,
    on_create_new_criterion_set_from_evaluation,
    on_finish_combining_sets,
    on_organization_window_start,
    on_select_criterion_set,
    on_select_evaluated_employee,
    on_select_evaluation_to_delete,
    on_select_filled_by_employee,
    on_skip_evaluation_type_description,
    on_toggle_criterion_set_for_combine,
    on_use_default_criterion_set,
    process_evaluation_type_code_input,
    process_evaluation_type_description_input,
    process_evaluation_type_name_input,
)
from app.tgbot.dialogs.evaluation.states import EvaluationDialog


def select_evaluation_type_window():
    """Create evaluation type selection window.

    Returns:
        Window: The configured evaluation type selection window.
    """
    return create_evaluation_type_select_window(
        state=EvaluationDialog.select_evaluation_type,
        message_text="Выберите тип оценки:",
        next_state=EvaluationDialog.select_organization,
        cancel_handler=on_cancel_evaluation,
        create_evaluation_type_state=EvaluationDialog.evaluation_type_name_input,
        use_scrolling=True,
        on_success_callback=_on_evaluation_type_selected,
    )


def evaluation_type_name_input_window():
    """Create evaluation type name input window."""
    return create_evaluation_type_name_input_window(
        state=EvaluationDialog.evaluation_type_name_input,
        process_name_handler=process_evaluation_type_name_input,
        back_state=EvaluationDialog.select_evaluation_type,
    )


def evaluation_type_code_input_window():
    """Create evaluation type code input window."""
    return create_evaluation_type_code_input_window(
        state=EvaluationDialog.evaluation_type_code_input,
        process_code_handler=process_evaluation_type_code_input,
        back_state=EvaluationDialog.evaluation_type_name_input,
    )


def evaluation_type_description_input_window():
    """Create evaluation type description input window."""
    return create_evaluation_type_description_input_window(
        state=EvaluationDialog.evaluation_type_description_input,
        process_description_handler=process_evaluation_type_description_input,
        skip_handler=on_skip_evaluation_type_description,
        back_state=EvaluationDialog.evaluation_type_code_input,
    )


def evaluation_type_confirm_window():
    """Create evaluation type confirm window."""
    return create_evaluation_type_confirm_window(
        state=EvaluationDialog.evaluation_type_confirm,
        confirm_handler=on_confirm_evaluation_type,
        back_state=EvaluationDialog.evaluation_type_description_input,
    )


def select_organization_window():
    """Create organization selection window.

    Returns:
        Window: The configured organization selection window.
    """
    return create_organization_select_window(
        state=EvaluationDialog.select_organization,
        message_text="Выберите организацию для замера:",
        next_state=EvaluationDialog.select_filled_by_employee,
        use_scrolling=True,
        on_success_callback=on_organization_window_start,
        switch_to=SwitchTo(
            Const("Назад"),
            id="back_evaluation_organization",
            state=EvaluationDialog.select_evaluation_type,
        ),
    )


def select_filled_by_employee_window():
    """Create filled by employee selection window.

    Returns:
        Window: The configured filled by employee selection window.
    """
    return Window(
        Format("Выберите сотрудника, который заполняет оценку:"),
        ScrollingGroup(
            Select(
                Format("{item.full_name}"),
                item_id_getter=lambda emp: emp.id,
                items="employees",
                id="select_filled_by_employee",
                on_click=on_select_filled_by_employee,
            ),
            id="scrolling_employees",
            width=1,
            height=10,
            when=lambda data, widget, manager: data.get("has_employees", False) and not data.get("filled_by_employee_id"),
            hide_on_single_page=True,
        ),
        SwitchTo(
            Const("Назад"),
            id="back_from_filled_by_employee",
            state=EvaluationDialog.select_evaluation_type,
        ),
        state=EvaluationDialog.select_filled_by_employee,
        getter=get_employees_list_data,
    )


def select_evaluated_employee_window():
    """Create evaluated employee selection window.

    Returns:
        Window: The configured evaluated employee selection window.
    """
    return Window(
        Format("Выберите сотрудника, о котором заполняется оценка:"),
        ScrollingGroup(
            Select(
                Format("{item.full_name}"),
                item_id_getter=lambda emp: emp.id,
                items="employees",
                id="select_evaluated_employee",
                on_click=on_select_evaluated_employee,
            ),
            id="scrolling_employees_evaluated",
            width=1,
            height=10,
            when="has_employees",
            hide_on_single_page=True,
        ),
        SwitchTo(
            Const("Назад"),
            id="back_from_evaluated_employee",
            state=EvaluationDialog.select_evaluation_type,
        ),
        state=EvaluationDialog.select_evaluated_employee,
        getter=get_employees_list_data,
    )


def select_criterion_set_window():
    """Create criterion set selection window.

    Returns:
        Window: The configured criterion set selection window.
    """
    return create_criterion_set_select_window(
        state=EvaluationDialog.select_criterion_set,
        message_text="Выберите набор критериев:",
        on_select_handler=on_select_criterion_set,
        on_use_default_handler=on_use_default_criterion_set,
        on_combine_handler=on_combine_criterion_sets,
        on_create_new_handler=on_create_new_criterion_set_from_evaluation,
        back_state=EvaluationDialog.select_evaluated_employee,
        use_scrolling=True,
        show_create_when_empty=True,
        auto_create_when_empty=True,
    )


def combine_criterion_sets_window():
    """Create criterion sets combination window.

    Returns:
        Window: The configured criterion sets combination window.
    """
    return Window(
        Format(
            "Выберите наборы критериев для комбинирования (минимум 2):\n\nВыбрано: {selected_count}"
        ),
        ScrollingGroup(
            Select(
                Format("{item[display_name]} {item[selected_marker]}"),
                item_id_getter=lambda cs: cs["id"] if isinstance(cs, dict) else cs.id,
                items="criterion_sets",
                id="toggle_criterion_set",
                on_click=on_toggle_criterion_set_for_combine,
            ),
            id="scrolling_criterion_sets_combine",
            width=1,
            height=10,
            when="has_criterion_sets",
            hide_on_single_page=True,
        ),
        Row(
            Button(
                text=Const("Объединить наборы ✅"),
                id="finish_combining",
                on_click=on_finish_combining_sets,
                when="can_combine",
            ),
        ),
        Back(Const("Назад")),
        state=EvaluationDialog.combine_criterion_sets,
        getter=get_criterion_sets_list_data,
    )


def select_evaluation_to_delete_window():
    """Create evaluation selection window for deletion.

    Returns:
        Window: The configured evaluation selection window.
    """
    return Window(
        Format("Выберите замер для удаления:"),
        ScrollingGroup(
            Select(
                Format("{item[display]}"),
                item_id_getter=lambda eval_item: str(eval_item["id"]),
                items="evaluations",
                id="select_evaluation_to_delete",
                on_click=on_select_evaluation_to_delete,
            ),
            id="scrolling_evaluations",
            width=1,
            height=10,
            when="has_evaluations",
            hide_on_single_page=True,
        ),
        Format(
            "Нет замеров для удаления.",
            when=lambda data, widget, manager: not data.get("has_evaluations", False),
        ),
        Cancel(
            Const("Назад"),
            id="back_to_evaluations_menu",
        ),
        state=EvaluationDialog.select_evaluation_to_delete,
        getter=get_evaluations_list_data_for_deletion,
    )
