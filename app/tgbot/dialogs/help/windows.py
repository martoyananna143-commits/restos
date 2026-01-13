"""Windows for help dialog."""

from pathlib import Path

from aiogram.types import ContentType
from aiogram_dialog import Window
from aiogram_dialog.widgets.kbd import Button, Row
from aiogram_dialog.widgets.media import StaticMedia
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


def get_static_dir() -> Path:
    """Get path to static directory.
    
    Returns:
        Path: Path to static directory.
    """
    return Path(__file__).parent / "static"


def help_main_window():
    """Create main help window.

    Returns:
        Window: The configured help main window.
    """
    return Window(
        Format("<b>{title}</b>\n\n{description}"),
        Row(
            Button(
                text=Const("🚀 Интерактивное обучение"),
                id="start_tutorial",
                on_click=on_start_tutorial,
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


# This function is no longer needed as we use individual windows
# def tutorial_step_window():
#     """Create tutorial step window with navigation.
#
#     Returns:
#         Window: The configured tutorial step window.
#     """
#     return Window(
#         Format("📚 **Обучение Restos**\n\n**Шаг {step_number}: {title}**\n\n{content}"),
#         Row(
#             Button(
#                 text=Const("⬅️ Назад"),
#                 id="prev_step",
#                 on_click=on_prev_step,
#                 when="show_prev_button",
#             ),
#             Button(
#                 text=Const("Далее ➡️"),
#                 id="next_step",
#                 on_click=on_next_step,
#                 when="show_next_button",
#             ),
#         ),
#         Row(
#             Button(
#                 text=Const("🏠 В меню помощи"),
#                 id="back_to_help",
#                 on_click=on_back_to_help_main,
#             ),
#             Button(
#                 text=Const("✅ Завершить"),
#                 id="finish_tutorial",
#                 on_click=on_finish_tutorial,
#                 when="is_final_step",
#             ),
#         ),
#         state=HelpDialog.step_1_welcome,  # Base state, will be switched programmatically
#         getter=get_tutorial_step_data,
#     )


# Individual step windows for better control
def step_1_welcome_window():
    """Step 1: Welcome window."""
    return Window(
        Format("📚 <b>Обучение Restos</b>\n\n<b>Шаг {step_number}: {title}</b>\n\n{content}"),
        Row(
            Button(
                text=Const("Далее ➡️"),
                id="next_step_1",
                on_click=on_step_1_next,
            ),
        ),
        Row(
            Button(
                text=Const("🏠 В меню помощи"),
                id="back_to_help_1",
                on_click=on_back_to_help_main,
            ),
        ),
        parse_mode="HTML",
        state=HelpDialog.step_1_welcome,
        getter=get_step_1_welcome_data,
    )


def step_2_organization_window():
    """Step 2: Organization setup window."""
    # Get path to static directory
    static_dir = get_static_dir()
    gif_path = static_dir / "org.mp4"
    
    return Window(
        StaticMedia(
            path=str(gif_path),
            type=ContentType.VIDEO,
        ),
        Format("📚 <b>Обучение Restos</b>\n\n<b>Шаг {step_number}: {title}</b>\n\n{content}"),
        Row(
            Button(
                text=Const("⬅️ Назад"),
                id="prev_step_2",
                on_click=on_step_2_prev,
            ),
            Button(
                text=Const("Далее ➡️"),
                id="next_step_2",
                on_click=on_step_2_next,
            ),
        ),
        Row(
            Button(
                text=Const("🏠 В меню помощи"),
                id="back_to_help_2",
                on_click=on_back_to_help_main,
            ),
        ),
        parse_mode="HTML",
        state=HelpDialog.step_2_organization,
        getter=get_step_2_organization_data,
    )


def step_3_employees_window():
    """Step 3: Employees setup window."""
    # Get path to static directory
    static_dir = get_static_dir()
    gif_path = static_dir / "empl.mp4"
    
    return Window(
        StaticMedia(
            path=str(gif_path),
            type=ContentType.VIDEO,
        ),
        Format("📚 <b>Обучение Restos</b>\n\n<b>Шаг {step_number}: {title}</b>\n\n{content}"),
        Row(
            Button(
                text=Const("⬅️ Назад"),
                id="prev_step_3",
                on_click=on_step_3_prev,
            ),
            Button(
                text=Const("Далее ➡️"),
                id="next_step_3",
                on_click=on_step_3_next,
            ),
        ),
        Row(
            Button(
                text=Const("🏠 В меню помощи"),
                id="back_to_help_3",
                on_click=on_back_to_help_main,
            ),
        ),
        parse_mode="HTML",
        state=HelpDialog.step_3_employees,
        getter=get_step_3_employees_data,
    )


def step_4_criteria_window():
    """Step 4: Criteria setup window."""
    # Get path to static directory
    static_dir = get_static_dir()
    video_path = static_dir / "crit.mp4"
    
    return Window(
        StaticMedia(
            path=str(video_path),
            type=ContentType.VIDEO,
        ),
        Format("📚 <b>Обучение Restos</b>\n\n<b>Шаг {step_number}: {title}</b>\n\n{content}"),
        Row(
            Button(
                text=Const("⬅️ Назад"),
                id="prev_step_4",
                on_click=on_step_4_prev,
            ),
            Button(
                text=Const("Далее ➡️"),
                id="next_step_4",
                on_click=on_step_4_next,
            ),
        ),
        Row(
            Button(
                text=Const("🏠 В меню помощи"),
                id="back_to_help_4",
                on_click=on_back_to_help_main,
            ),
        ),
        parse_mode="HTML",
        state=HelpDialog.step_4_criteria,
        getter=get_step_4_criteria_data,
    )


def step_5_sets_window():
    """Step 5: Criterion sets window."""
    # Get path to static directory
    static_dir = get_static_dir()
    video_path = static_dir / "set.mp4"
    
    return Window(
        StaticMedia(
            path=str(video_path),
            type=ContentType.VIDEO,
        ),
        Format("📚 <b>Обучение Restos</b>\n\n<b>Шаг {step_number}: {title}</b>\n\n{content}"),
        Row(
            Button(
                text=Const("⬅️ Назад"),
                id="prev_step_5",
                on_click=on_step_5_prev,
            ),
            Button(
                text=Const("Далее ➡️"),
                id="next_step_5",
                on_click=on_step_5_next,
            ),
        ),
        Row(
            Button(
                text=Const("🏠 В меню помощи"),
                id="back_to_help_5",
                on_click=on_back_to_help_main,
            ),
        ),
        parse_mode="HTML",
        state=HelpDialog.step_5_sets,
        getter=get_step_5_sets_data,
    )


def step_6_evaluation_window():
    """Step 6: Evaluation process window."""
    # Get path to static directory
    static_dir = get_static_dir()
    video_path = static_dir / "eval.mp4"
    
    return Window(
        StaticMedia(
            path=str(video_path),
            type=ContentType.VIDEO,
        ),
        Format("📚 <b>Обучение Restos</b>\n\n<b>Шаг {step_number}: {title}</b>\n\n{content}"),
        Row(
            Button(
                text=Const("⬅️ Назад"),
                id="prev_step_6",
                on_click=on_step_6_prev,
            ),
            Button(
                text=Const("Далее ➡️"),
                id="next_step_6",
                on_click=on_step_6_next,
            ),
        ),
        Row(
            Button(
                text=Const("🏠 В меню помощи"),
                id="back_to_help_6",
                on_click=on_back_to_help_main,
            ),
        ),
        parse_mode="HTML",
        state=HelpDialog.step_6_evaluation,
        getter=get_step_6_evaluation_data,
    )


def step_7_analytics_window():
    """Step 7: Analytics and reports window."""
    # Get path to static directory
    static_dir = get_static_dir()
    video_path = static_dir / "base.mp4"
    
    return Window(
        StaticMedia(
            path=str(video_path),
            type=ContentType.VIDEO,
        ),
        Format("📚 <b>Обучение Restos</b>\n\n<b>Шаг {step_number}: {title}</b>\n\n{content}"),
        Row(
            Button(
                text=Const("⬅️ Назад"),
                id="prev_step_7",
                on_click=on_step_7_prev,
            ),
            Button(
                text=Const("Далее ➡️"),
                id="next_step_7",
                on_click=on_step_7_next,
            ),
        ),
        Row(
            Button(
                text=Const("🏠 В меню помощи"),
                id="back_to_help_7",
                on_click=on_back_to_help_main,
            ),
        ),
        parse_mode="HTML",
        state=HelpDialog.step_7_analytics,
        getter=get_step_7_analytics_data,
    )


def step_8_advanced_window():
    """Step 8: Advanced features window."""
    # Get path to static directory
    static_dir = get_static_dir()
    video_path = static_dir / "ai.mp4"
    
    return Window(
        StaticMedia(
            path=str(video_path),
            type=ContentType.VIDEO,
        ),
        Format("📚 <b>Обучение Restos</b>\n\n<b>Шаг {step_number}: {title}</b>\n\n{content}"),
        Row(
            Button(
                text=Const("⬅️ Назад"),
                id="prev_step_8",
                on_click=on_step_8_prev,
            ),
            Button(
                text=Const("Далее ➡️"),
                id="next_step_8",
                on_click=on_step_8_next,
            ),
        ),
        Row(
            Button(
                text=Const("🏠 В меню помощи"),
                id="back_to_help_8",
                on_click=on_back_to_help_main,
            ),
        ),
        parse_mode="HTML",
        state=HelpDialog.step_8_advanced,
        getter=get_step_8_advanced_data,
    )


def final_step_window():
    """Final step: Congratulations window."""
    return Window(
        Format("📚 <b>Обучение Restos</b>\n\n<b>Шаг {step_number}: {title}</b>\n\n{content}"),
        Row(
            Button(
                text=Const("⬅️ Назад"),
                id="prev_final",
                on_click=on_final_prev,
            ),
            Button(
                text=Const("🎉 Завершить обучение"),
                id="finish_tutorial_final",
                on_click=on_finish_tutorial,
            ),
        ),
        Row(
            Button(
                text=Const("🏠 В меню помощи"),
                id="back_to_help_final",
                on_click=on_back_to_help_main,
            ),
        ),
        parse_mode="HTML",
        state=HelpDialog.final_step,
        getter=get_final_step_data,
    )
