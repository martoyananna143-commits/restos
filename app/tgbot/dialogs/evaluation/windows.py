"""Windows for evaluation dialog."""

from aiogram_dialog import DialogManager, Window
from aiogram_dialog.widgets.common import Whenable
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import (
    Back,
    Button,
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
    get_add_comment_data,
    get_criterion_sets_list_data,
    get_current_question_data,
    get_employees_list_data,
    get_report_generation_data,
)
from app.tgbot.dialogs.evaluation.handlers import (
    _on_evaluation_type_selected,
    on_answer_no,
    on_answer_yes,
    on_back_to_last_question,
    on_cancel_evaluation,
    on_combine_criterion_sets,
    on_confirm_evaluation_type,
    on_create_new_criterion_set_from_evaluation,
    on_finish_combining_sets,
    on_generate_excel,
    on_generate_pdf,
    on_next_question,
    on_organization_window_start,
    on_prev_question,
    on_select_criterion_set,
    on_select_evaluated_employee,
    on_select_filled_by_employee,
    on_send_to_employee,
    on_skip_comment,
    on_skip_evaluation_type_description,
    on_skip_pdf,
    on_toggle_criterion_set_for_combine,
    on_use_default_criterion_set,
    process_comment_input,
    process_evaluation_type_code_input,
    process_evaluation_type_description_input,
    process_evaluation_type_name_input,
    process_number_input,
    process_text_input,
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
        ),
        Back(Const("Назад")),
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
        ),
        Back(Const("Назад")),
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


def is_first(data: dict, widget: Whenable, manager: DialogManager):
    return data.get("current_question_index") == 0


def question_loop_window():
    """Create question loop window.

    Returns:
        Window: The configured question loop window.
    """
    return Window(
        Format("{question_text}"),
        Row(
            Button(
                text=Const("Ответить ➡️"),
                id="answer_question",
                on_click=on_next_question,
            ),
        ),
        SwitchTo(
            Const("Назад"),
            id="back_qloop",
            state=EvaluationDialog.select_criterion_set,
            when=is_first,
        ),
        Button(
            Const("Назад"),
            id="back_qloop_not_first",
            on_click=on_prev_question,
            when="current_question_index",
        ),
        state=EvaluationDialog.question_loop,
        getter=get_current_question_data,
    )


def answer_question_window():
    """Create answer question window for boolean type.

    Returns:
        Window: The configured answer question window.
    """
    return Window(
        Format("{question_text}\n\nВыберите ответ:"),
        Row(
            Button(
                text=Const("Да ✅"),
                id="answer_yes",
                on_click=on_answer_yes,
            ),
            Button(
                text=Const("Нет ❌"),
                id="answer_no",
                on_click=on_answer_no,
            ),
        ),
        SwitchTo(
            Const("Назад"),
            id="back_question_window",
            state=EvaluationDialog.question_loop,
        ),
        state=EvaluationDialog.answer_question,
        getter=get_current_question_data,
    )


def answer_text_window():
    """Create answer text input window for string type.

    Returns:
        Window: The configured answer text input window.
    """
    return Window(
        Format("{question_text}\n\nВведите текст:"),
        MessageInput(process_text_input),
        SwitchTo(
            Const("Назад"),
            id="back_answer_text_window",
            state=EvaluationDialog.question_loop,
        ),
        state=EvaluationDialog.answer_text,
        getter=get_current_question_data,
    )


def answer_number_window():
    """Create answer number input window for number type.

    Returns:
        Window: The configured answer number input window.
    """
    return Window(
        Format("{question_text}\n\nВведите число:"),
        MessageInput(process_number_input),
        SwitchTo(
            Const("Назад"),
            id="back_answer_number_window",
            state=EvaluationDialog.question_loop,
        ),
        state=EvaluationDialog.answer_number,
        getter=get_current_question_data,
    )


def add_comment_window():
    """Create add comment window.

    Returns:
        Window: The configured add comment window.
    """
    return Window(
        Format("Оставить комментарий к ответу? (или нажмите 'Пропустить'):"),
        MessageInput(process_comment_input),
        Row(
            Button(
                text=Const("Пропустить ⏭️"),
                id="skip_comment",
                on_click=on_skip_comment,
            ),
        ),
        SwitchTo(
            Const("Назад"),
            id="back_to_answer_question",
            state=EvaluationDialog.answer_question,
            when="is_boolean_question",
        ),
        SwitchTo(
            Const("Назад"),
            id="back_to_answer_text",
            state=EvaluationDialog.answer_text,
            when="is_string_question",
        ),
        SwitchTo(
            Const("Назад"),
            id="back_to_answer_number",
            state=EvaluationDialog.answer_number,
            when="is_number_question",
        ),
        state=EvaluationDialog.add_comment,
        getter=get_add_comment_data,
    )


def send_to_employee_window():
    """Create send to employee window.

    Returns:
        Window: The configured send to employee window.
    """
    return Window(
        Format(
            "Все вопросы пройдены!\n\n"
            "Нажмите 'Отправить сотруднику' для завершения замера и отправки результатов."
        ),
        Row(
            Button(
                text=Const("Отправить сотруднику 📤"),
                id="send_to_employee",
                on_click=on_send_to_employee,
            ),
        ),
        Button(
            Const("Назад"),
            id="back_to_last_question",
            on_click=on_back_to_last_question,
        ),
        state=EvaluationDialog.send_to_employee,
    )


def generate_pdf_window():
    """Create generate PDF/Excel window.

    Returns:
        Window: The configured generate PDF/Excel window.
    """
    return Window(
        Format("{message_text}"),
        Row(
            Button(
                text=Const("Сгенерировать PDF 📄"),
                id="generate_pdf",
                on_click=on_generate_pdf,
                when="show_pdf_button",
            ),
            Button(
                text=Const("Сгенерировать Excel 📊"),
                id="generate_excel",
                on_click=on_generate_excel,
                when="show_excel_button",
            ),
        ),
        Row(
            Button(
                text=Const("Завершить ✅"),
                id="skip_pdf",
                on_click=on_skip_pdf,
                when="both_generated",
            ),
            Button(
                text=Const("Пропустить ⏭️"),
                id="skip_pdf",
                on_click=on_skip_pdf,
                when="show_skip_button",
            ),
        ),
        state=EvaluationDialog.generate_pdf,
        getter=get_report_generation_data,
    )
