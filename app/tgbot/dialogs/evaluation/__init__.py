"""Evaluation dialog."""

from aiogram_dialog import Dialog

from app.tgbot.dialogs.evaluation.windows import (
    combine_criterion_sets_window,
    evaluation_type_confirm_window,
    evaluation_type_code_input_window,
    evaluation_type_description_input_window,
    evaluation_type_name_input_window,
    select_criterion_set_window,
    select_evaluated_employee_window,
    select_evaluation_to_delete_window,
    select_evaluation_type_window,
    select_filled_by_employee_window,
    select_organization_window,
)


def evaluation_dialog():
    """Create evaluation dialog."""
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
        select_evaluation_to_delete_window(),
    )
