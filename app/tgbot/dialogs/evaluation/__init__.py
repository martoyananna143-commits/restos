"""Evaluation dialog."""

from aiogram_dialog import Dialog

from app.tgbot.dialogs.evaluation.windows import (
    add_comment_window,
    answer_number_window,
    answer_question_window,
    answer_text_window,
    combine_criterion_sets_window,
    evaluation_type_confirm_window,
    evaluation_type_code_input_window,
    evaluation_type_description_input_window,
    evaluation_type_name_input_window,
    generate_pdf_window,
    question_loop_window,
    select_criterion_set_window,
    select_evaluated_employee_window,
    select_evaluation_type_window,
    select_filled_by_employee_window,
    select_organization_window,
    send_to_employee_window,
)


def evaluation_dialog():
    """Create evaluation dialog.

    Returns:
        Dialog: The configured evaluation dialog.
    """
    return Dialog(
        select_evaluation_type_window(),
        evaluation_type_name_input_window(),
        evaluation_type_code_input_window(),
        evaluation_type_description_input_window(),
        evaluation_type_confirm_window(),
        select_organization_window(),
        select_filled_by_employee_window(),
        select_evaluated_employee_window(),
        select_criterion_set_window(),
        combine_criterion_sets_window(),
        question_loop_window(),
        answer_question_window(),
        answer_text_window(),
        answer_number_window(),
        add_comment_window(),
        send_to_employee_window(),
        generate_pdf_window(),
    )
