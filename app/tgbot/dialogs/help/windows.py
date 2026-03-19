"""Windows for help dialog."""

from aiogram_dialog import Window
from aiogram_dialog.widgets.kbd import Button, Row
from aiogram_dialog.widgets.text import Const, Format

from app.tgbot.dialogs.help.getters import (
    get_final_step_data,
    get_help_main_data,
    get_step_1_welcome_data,
    get_step_2_organization_data,
    get_step_3_employees_data,
    get_step_4_criteria_data,
    get_step_5_sets_data,
    get_step_6_evaluation_data,
    get_step_7_analytics_data,
    get_step_8_advanced_data,
)
from app.tgbot.dialogs.help.handlers import (
    on_back_to_help_main,
    on_cancel_help,
    on_final_prev,
    on_finish_tutorial,
    on_skip_tutorial,
    on_start_tutorial,
    on_step_1_next,
    on_step_2_next,
    on_step_2_prev,
    on_step_3_next,
    on_step_3_prev,
    on_step_4_next,
    on_step_4_prev,
    on_step_5_next,
    on_step_5_prev,
    on_step_6_next,
    on_step_6_prev,
    on_step_7_next,
    on_step_7_prev,
    on_step_8_next,
    on_step_8_prev,
)
from app.tgbot.dialogs.help.states import HelpDialog


_STEP_FMT = "📚 <b>Обучение Restos</b>\n\n<b>Шаг {step_number}: {title}</b>\n\n{content}"


def help_main_window():
    """Create main help window."""
    return Window(
        Format("<b>{title}</b>\n\n{description}"),
        Row(
            Button(
                text=Const("🚀 Интерактивное обучение"),
                id="start_tutorial",
                on_click=on_start_tutorial,
            ),
        ),
        Row(
            Button(
                text=Const("⏭️ Пропустить обучение"),
                id="skip_tutorial",
                on_click=on_skip_tutorial,
            ),
        ),
        Button(
            text=Const("⬅️ В главное меню"),
            id="cancel_help",
            on_click=on_cancel_help,
            when="has_organization",
        ),
        parse_mode="HTML",
        state=HelpDialog.main_help,
        getter=get_help_main_data,
    )


def step_1_welcome_window():
    """Step 1: Welcome window."""
    return Window(
        Format(_STEP_FMT),
        Row(
            Button(text=Const("Далее ➡️"), id="next_step_1", on_click=on_step_1_next),
        ),
        Row(
            Button(text=Const("🏠 В меню помощи"), id="back_to_help_1", on_click=on_back_to_help_main),
        ),
        parse_mode="HTML",
        state=HelpDialog.step_1_welcome,
        getter=get_step_1_welcome_data,
    )


def step_2_organization_window():
    """Step 2: Organization setup window."""
    return Window(
        Format(_STEP_FMT),
        Row(
            Button(text=Const("⬅️ Назад"), id="prev_step_2", on_click=on_step_2_prev),
            Button(text=Const("Далее ➡️"), id="next_step_2", on_click=on_step_2_next),
        ),
        Row(
            Button(text=Const("🏠 В меню помощи"), id="back_to_help_2", on_click=on_back_to_help_main),
        ),
        parse_mode="HTML",
        state=HelpDialog.step_2_organization,
        getter=get_step_2_organization_data,
    )


def step_3_employees_window():
    """Step 3: Employees setup window."""
    return Window(
        Format(_STEP_FMT),
        Row(
            Button(text=Const("⬅️ Назад"), id="prev_step_3", on_click=on_step_3_prev),
            Button(text=Const("Далее ➡️"), id="next_step_3", on_click=on_step_3_next),
        ),
        Row(
            Button(text=Const("🏠 В меню помощи"), id="back_to_help_3", on_click=on_back_to_help_main),
        ),
        parse_mode="HTML",
        state=HelpDialog.step_3_employees,
        getter=get_step_3_employees_data,
    )


def step_4_criteria_window():
    """Step 4: Criteria setup window."""
    return Window(
        Format(_STEP_FMT),
        Row(
            Button(text=Const("⬅️ Назад"), id="prev_step_4", on_click=on_step_4_prev),
            Button(text=Const("Далее ➡️"), id="next_step_4", on_click=on_step_4_next),
        ),
        Row(
            Button(text=Const("🏠 В меню помощи"), id="back_to_help_4", on_click=on_back_to_help_main),
        ),
        parse_mode="HTML",
        state=HelpDialog.step_4_criteria,
        getter=get_step_4_criteria_data,
    )


def step_5_sets_window():
    """Step 5: Criterion sets window."""
    return Window(
        Format(_STEP_FMT),
        Row(
            Button(text=Const("⬅️ Назад"), id="prev_step_5", on_click=on_step_5_prev),
            Button(text=Const("Далее ➡️"), id="next_step_5", on_click=on_step_5_next),
        ),
        Row(
            Button(text=Const("🏠 В меню помощи"), id="back_to_help_5", on_click=on_back_to_help_main),
        ),
        parse_mode="HTML",
        state=HelpDialog.step_5_sets,
        getter=get_step_5_sets_data,
    )


def step_6_evaluation_window():
    """Step 6: Evaluation process window."""
    return Window(
        Format(_STEP_FMT),
        Row(
            Button(text=Const("⬅️ Назад"), id="prev_step_6", on_click=on_step_6_prev),
            Button(text=Const("Далее ➡️"), id="next_step_6", on_click=on_step_6_next),
        ),
        Row(
            Button(text=Const("🏠 В меню помощи"), id="back_to_help_6", on_click=on_back_to_help_main),
        ),
        parse_mode="HTML",
        state=HelpDialog.step_6_evaluation,
        getter=get_step_6_evaluation_data,
    )


def step_7_analytics_window():
    """Step 7: Analytics and reports window."""
    return Window(
        Format(_STEP_FMT),
        Row(
            Button(text=Const("⬅️ Назад"), id="prev_step_7", on_click=on_step_7_prev),
            Button(text=Const("Далее ➡️"), id="next_step_7", on_click=on_step_7_next),
        ),
        Row(
            Button(text=Const("🏠 В меню помощи"), id="back_to_help_7", on_click=on_back_to_help_main),
        ),
        parse_mode="HTML",
        state=HelpDialog.step_7_analytics,
        getter=get_step_7_analytics_data,
    )


def step_8_advanced_window():
    """Step 8: Advanced features window."""
    return Window(
        Format(_STEP_FMT),
        Row(
            Button(text=Const("⬅️ Назад"), id="prev_step_8", on_click=on_step_8_prev),
            Button(text=Const("Далее ➡️"), id="next_step_8", on_click=on_step_8_next),
        ),
        Row(
            Button(text=Const("🏠 В меню помощи"), id="back_to_help_8", on_click=on_back_to_help_main),
        ),
        parse_mode="HTML",
        state=HelpDialog.step_8_advanced,
        getter=get_step_8_advanced_data,
    )


def final_step_window():
    """Final step: Congratulations window."""
    return Window(
        Format(_STEP_FMT),
        Row(
            Button(text=Const("⬅️ Назад"), id="prev_final", on_click=on_final_prev),
            Button(text=Const("🎉 Завершить обучение"), id="finish_tutorial_final", on_click=on_finish_tutorial),
        ),
        Row(
            Button(text=Const("🏠 В меню помощи"), id="back_to_help_final", on_click=on_back_to_help_main),
        ),
        parse_mode="HTML",
        state=HelpDialog.final_step,
        getter=get_final_step_data,
    )
