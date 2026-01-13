"""Windows for greeting dialog."""

from aiogram_dialog import Window
from aiogram_dialog.widgets.kbd import Back, Button, Cancel, Next, Row, Start, SwitchTo
from aiogram_dialog.widgets.text import Const, Format

from app.tgbot.dialogs.analytics.states import AnalyticsDialog
from app.tgbot.dialogs.greeting.getters import get_greeting_data
from app.tgbot.dialogs.greeting.handlers import (
    on_create_criterion_clicked,
    on_create_criterion_set_clicked,
    on_create_employee_clicked,
    on_create_evaluation_clicked,
    on_edit_employee_clicked,
    on_help_clicked,
    on_start_work_clicked,
)
from app.tgbot.dialogs.greeting.states import GreetingDialog
from app.tgbot.dialogs.organization.states import OrganizationDialog


def greeting_window():
    """Create greeting window.

    Returns:
        Window: The configured greeting window.
    """
    return Window(
        Format("{greeting_text}"),
        Row(
            SwitchTo(
                text=Const("Организации 🏢"),
                id="organizations_menu",
                state=GreetingDialog.organizations_menu,
                when="is_administrator",
            ),
            SwitchTo(
                text=Const("Сотрудники 👥"),
                id="employees_menu",
                state=GreetingDialog.employees_menu,
                when="is_administrator",
            ),
        ),
        Row(
            SwitchTo(
                text=Const("Оценки 📊"),
                id="evaluations_menu",
                state=GreetingDialog.evaluations_menu,
            ),
        ),
        Row(
            SwitchTo(
                text=Const("Критерии и наборы 📋"),
                id="criteria_and_sets_menu",
                state=GreetingDialog.criteria_and_sets_menu,
                when="is_administrator",
            ),
            Start(
                text=Const("Аналитика 📈"),
                id="analytics",
                state=AnalyticsDialog.select_organization,
            ),
        ),
        Row(
            Button(
                text=Const("Помощь ❓"),
                id="help_button",
                on_click=on_help_clicked,
            ),
        ),
        state=GreetingDialog.greeting,
        getter=get_greeting_data,
    )


def organizations_menu_window():
    """Create organizations menu window.

    Returns:
        Window: The configured organizations menu window.
    """
    return Window(
        Const("Управление организациями:\n\nВыберите действие:"),
        Start(
            text=Const("Создать организацию ➕"),
            id="create_organization",
            state=OrganizationDialog.name_input,
        ),
        Start(
            text=Const("Редактировать организацию ✏️"),
            id="edit_organization",
            state=OrganizationDialog.select_organization_to_edit,
        ),
        Back(Const("Назад ⬅️")),
        state=GreetingDialog.organizations_menu,
    )


def employees_menu_window():
    """Create employees menu window.

    Returns:
        Window: The configured employees menu window.
    """
    return Window(
        Const("Управление сотрудниками\n\nВыберите действие:"),
        Button(
            text=Const("Создать сотрудника ➕"),
            id="create_employee",
            on_click=on_create_employee_clicked,
        ),
        Button(
            text=Const("Редактировать сотрудника ✏️"),
            id="edit_employee",
            on_click=on_edit_employee_clicked,
        ),
        SwitchTo(
            text=Const("Назад"),
            id="back_greeting",
            state=GreetingDialog.greeting,
        ),
        state=GreetingDialog.employees_menu,
    )


def criteria_and_sets_menu_window():
    """Create criteria and sets menu window.

    Returns:
        Window: The configured criteria and sets menu window.
    """
    return Window(
        Const("Управление критериями и наборами\n\nВыберите действие:"),
        Row(
            Button(
                text=Const("Критерии ➕"),
                id="create_criterion",
                on_click=on_create_criterion_clicked,
            ),
        ),
        Row(
            Button(
                text=Const("Управление наборами 📋"),
                id="manage_criterion_sets",
                on_click=on_create_criterion_set_clicked,
            ),
        ),
        SwitchTo(
            text=Const("Назад"),
            id="back_greeting",
            state=GreetingDialog.greeting,
        ),
        state=GreetingDialog.criteria_and_sets_menu,
    )


def evaluations_menu_window():
    """Create evaluations menu window.

    Returns:
        Window: The configured evaluations menu window.
    """
    return Window(
        Const("Управление оценками:\n\nВыберите действие:"),
        Row(
            Button(
                text=Const("Сделать замер 📊"),
                id="create_evaluation",
                on_click=on_create_evaluation_clicked,
            ),
        ),
        SwitchTo(
            text=Const("Назад"),
            id="back_greeting_eva",
            state=GreetingDialog.greeting,
        ),
        state=GreetingDialog.evaluations_menu,
    )
