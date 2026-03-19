"""Windows for employee dialog."""

from aiogram_dialog import Window
from aiogram_dialog.widgets.input import MessageInput
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

from app.tgbot.dialogs.common.organization import create_organization_select_window
from app.tgbot.dialogs.employee.getters import (
    get_employee_form_data,
    get_employees_list_data_for_edit,
)
from app.tgbot.dialogs.employee.handlers import (
    get_roles_data,
    on_add_more_no,
    on_add_more_yes,
    on_cancel_employee,
    on_confirm_employee,
    on_create_organization_from_employee,
    on_edit_employee_full_name,
    on_edit_employee_phone,
    on_edit_employee_position,
    on_edit_employee_role,
    on_save_employee_changes,
    on_select_employee_to_edit,
    on_select_role,
    on_skip_phone,
    on_skip_position,
    process_full_name_input,
    process_phone_input,
    process_position_input,
)
from app.tgbot.dialogs.employee.states import EmployeeDialog


async def _on_employee_org_success(organization, dialog_manager):
    """Save organization to middleware_data for employee dialog."""
    dialog_manager.middleware_data["organization"] = organization


def select_organization_window():
    """Create organization selection window.

    Returns:
        Window: The configured organization selection window.
    """
    return create_organization_select_window(
        state=EmployeeDialog.select_organization,
        message_text="Выберите организацию для сотрудника:",
        next_state=EmployeeDialog.full_name_input,
        cancel_handler=on_cancel_employee,
        create_organization_handler=on_create_organization_from_employee,
        use_scrolling=True,
        on_success_callback=_on_employee_org_success,
    )


def select_organization_for_edit_window():
    """Create organization selection window for editing employee.

    Returns:
        Window: The configured organization selection window.
    """
    return create_organization_select_window(
        state=EmployeeDialog.select_organization_for_edit,
        message_text="Выберите организацию для редактирования сотрудника:",
        next_state=EmployeeDialog.select_employee_to_edit,
        cancel_handler=on_cancel_employee,
        create_organization_handler=on_create_organization_from_employee,
        use_scrolling=True,
        on_success_callback=_on_employee_org_success,
    )


def select_employee_to_edit_window():
    """Create employee selection window for editing.

    Returns:
        Window: The configured employee selection window.
    """
    return Window(
        Format("Выберите сотрудника для редактирования:"),
        ScrollingGroup(
            Select(
                Format("{item.full_name} - {item.position}"),
                item_id_getter=lambda emp: emp.id,
                items="employees",
                id="select_employee_to_edit",
                on_click=on_select_employee_to_edit,
            ),
            id="scrolling_employees",
            width=1,
            height=10,
            when="has_employees",
            hide_on_single_page=True,
        ),
        Cancel(Const("Назад ⬅️")),
        state=EmployeeDialog.select_employee_to_edit,
        getter=get_employees_list_data_for_edit,
    )


def edit_menu_window():
    """Create edit menu window for existing employee.

    Returns:
        Window: The configured edit menu window.
    """
    return Window(
        Format(
            "Редактирование сотрудника:\n\n"
            "ФИО: {full_name}\n"
            "Должность: {position}\n"
            "Телефон: {phone}\n"
            "Роль: {employee_type_name}\n\n"
            "Что вы хотите изменить?"
        ),
        Row(
            Button(
                text=Const("Изменить ФИО ✏️"),
                id="edit_full_name",
                on_click=on_edit_employee_full_name,
            ),
        ),
        Row(
            Button(
                text=Const("Изменить должность 💼"),
                id="edit_position",
                on_click=on_edit_employee_position,
            ),
        ),
        Row(
            Button(
                text=Const("Изменить телефон 📞"),
                id="edit_phone",
                on_click=on_edit_employee_phone,
            ),
        ),
        Row(
            Button(
                text=Const("Настройка роли 🔑"),
                id="edit_role",
                on_click=on_edit_employee_role,
            ),
        ),
        Row(
            Button(
                text=Const("Сохранить изменения ✅"),
                id="save_changes",
                on_click=on_save_employee_changes,
            ),
        ),
        Back(Const("Назад")),
        state=EmployeeDialog.edit_menu,
        getter=get_employee_form_data,
    )


def full_name_input_window():
    """Create full name input window.

    Returns:
        Window: The configured full name input window.
    """
    return Window(
        Format(
            "Введите ФИО сотрудника:",
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        Format("Введите новое ФИО сотрудника:", when="is_editing"),
        MessageInput(process_full_name_input),
        SwitchTo(
            Const("Назад"),
            id="back_edit_full_name_input_window",
            state=EmployeeDialog.edit_menu,
            when="is_editing",
        ),
        Cancel(
            Const("Назад ⬅️"),
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        state=EmployeeDialog.full_name_input,
        getter=get_employee_form_data,
    )


def position_input_window():
    """Create position input window.

    Returns:
        Window: The configured position input window.
    """
    return Window(
        Format(
            "Введите должность сотрудника (или нажмите 'Пропустить'):",
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        Format(
            "Введите новую должность сотрудника (или нажмите 'Пропустить'):",
            when="is_editing",
        ),
        MessageInput(process_position_input),
        Row(
            Button(
                text=Const("Пропустить ⏭️"),
                id="skip_position",
                on_click=on_skip_position,
            ),
            SwitchTo(
                Const("Назад"),
                id="back_position_input_window",
                state=EmployeeDialog.edit_menu,
                when="is_editing",
            ),
            Back(
                Const("Назад"),
                when=lambda data, widget, manager: not data.get("is_editing", False),
            ),
        ),
        state=EmployeeDialog.position_input,
        getter=get_employee_form_data,
    )


def phone_input_window():
    """Create phone input window.

    Returns:
        Window: The configured phone input window.
    """
    return Window(
        Format(
            "Введите телефон сотрудника (или нажмите 'Пропустить'):",
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        Format(
            "Введите новый телефон сотрудника (или нажмите 'Пропустить'):",
            when="is_editing",
        ),
        MessageInput(process_phone_input),
        Row(
            Button(
                text=Const("Пропустить ⏭️"),
                id="skip_phone",
                on_click=on_skip_phone,
            ),
            SwitchTo(
                Const("Назад"),
                id="back_phone_input_window",
                state=EmployeeDialog.edit_menu,
                when="is_editing",
            ),
            Back(
                Const("Назад"),
                when=lambda data, widget, manager: not data.get("is_editing", False),
            ),
        ),
        state=EmployeeDialog.phone_input,
        getter=get_employee_form_data,
    )


def confirm_window():
    """Create confirm window.

    Returns:
        Window: The configured confirm window.
    """
    return Window(
        Format(
            "Проверьте данные сотрудника:\n\n"
            "ФИО: {full_name}\n"
            "Должность: {position}\n"
            "Телефон: {phone}\n"
            "Роль: {employee_type_name}\n\n"
            "Всё верно?",
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        Format(
            "Проверьте изменения сотрудника:\n\n"
            "ФИО: {full_name}\n"
            "Должность: {position}\n"
            "Телефон: {phone}\n"
            "Роль: {employee_type_name}\n\n"
            "Сохранить изменения?",
            when="is_editing",
        ),
        Row(
            Button(
                text=Const("Подтвердить ✅"),
                id="confirm",
                on_click=on_confirm_employee,
            ),
            SwitchTo(
                Const("Назад"),
                id="back_confirm_window",
                state=EmployeeDialog.edit_menu,
                when="is_editing",
            ),
            Back(
                Const("Назад"),
                when=lambda data, widget, manager: not data.get("is_editing", False),
            ),
        ),
        state=EmployeeDialog.confirm,
        getter=get_employee_form_data,
    )


def select_role_window():
    """Select employee role (employee_type)."""
    return Window(
        Const("Выберите роль для сотрудника 🔑\n"),
        Select(
            Format("{item[display]}"),
            item_id_getter=lambda role: role["id"],
            items="roles",
            id="select_role",
            on_click=on_select_role,
        ),
        SwitchTo(
            Const("Назад ⬅️"),
            id="back_from_select_role",
            state=EmployeeDialog.edit_menu,
        ),
        state=EmployeeDialog.select_role,
        getter=get_roles_data,
    )


def add_more_window():
    """Create add more window.

    Returns:
        Window: The configured add more window.
    """
    return Window(
        Const("Добавить еще одного сотрудника?"),
        Row(
            Button(
                text=Const("Да ➕"),
                id="add_more_yes",
                on_click=on_add_more_yes,
            ),
            Button(
                text=Const("Нет, завершить ✅"),
                id="add_more_no",
                on_click=on_add_more_no,
            ),
        ),
        state=EmployeeDialog.add_more,
    )
