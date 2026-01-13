"""Windows for organization dialog."""

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

from app.tgbot.dialogs.organization.getters import (
    get_employees_list_data_for_management,
    get_invitation_data,
    get_organization_check_data,
    get_organization_form_data,
    get_organizations_list_data,
)
from app.tgbot.dialogs.organization.handlers import (
    on_confirm_organization,
    on_continue_to_main_menu,
    on_edit_organization_address,
    on_edit_organization_code,
    on_edit_organization_name,
    on_edit_organization_phone,
    on_fire_employee,
    on_invite_employee,
    on_manage_employees,
    on_restore_employee,
    on_save_organization_changes,
    on_select_organization_to_edit,
    on_skip_address,
    on_skip_phone,
    process_address_input,
    process_code_input,
    process_name_input,
    process_phone_input,
)
from app.tgbot.dialogs.organization.states import OrganizationDialog


def check_organization_window():
    """Create organization check window.

    Returns:
        Window: The configured organization check window.
    """
    return Window(
        Format("{message_text}"),
        Row(
            SwitchTo(
                text=Const("Создать организацию ➕"),
                id="create_organization",
                state=OrganizationDialog.name_input,
                when="has_not_organization",
            ),
        ),
        Cancel(Const("Назад")),
        state=OrganizationDialog.check_organization,
        getter=get_organization_check_data,
    )


def name_input_window():
    """Create name input window.

    Returns:
        Window: The configured name input window.
    """
    return Window(
        Format(
            "Введите название организации:",
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        Format("Введите новое название организации:", when="is_editing"),
        MessageInput(process_name_input),
        SwitchTo(
            Const("Назад"),
            id="back_org_name_input_edit_window",
            state=OrganizationDialog.edit_menu,
            when="is_editing",
        ),
        Cancel(
            Const("Назад"),
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        state=OrganizationDialog.name_input,
        getter=get_organization_form_data,
    )


def code_input_window():
    """Create code input window.

    Returns:
        Window: The configured code input window.
    """
    return Window(
        Format(
            "Введите код организации (уникальный идентификатор):",
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        Format(
            "Введите новый код организации (уникальный идентификатор):",
            when="is_editing",
        ),
        MessageInput(process_code_input),
        SwitchTo(
            Const("Назад"),
            id="back_org_code_input_edit_window",
            state=OrganizationDialog.edit_menu,
            when="is_editing",
        ),
        Back(
            Const("Назад"),
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        state=OrganizationDialog.code_input,
        getter=get_organization_form_data,
    )


def address_input_window():
    """Create address input window.

    Returns:
        Window: The configured address input window.
    """
    return Window(
        Format(
            "Введите адрес организации (или нажмите 'Пропустить'):",
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        Format(
            "Введите новый адрес организации (или нажмите 'Пропустить'):",
            when="is_editing",
        ),
        MessageInput(process_address_input),
        Row(
            Button(
                text=Const("Пропустить ⏭️"),
                id="skip_address",
                on_click=on_skip_address,
            ),
            SwitchTo(
                Const("Назад"),
                id="back_org_address_input_edit_window",
                state=OrganizationDialog.edit_menu,
                when="is_editing",
            ),
            Back(
                Const("Назад"),
                when=lambda data, widget, manager: not data.get("is_editing", False),
            ),
        ),
        state=OrganizationDialog.address_input,
        getter=get_organization_form_data,
    )


def phone_input_window():
    """Create phone input window.

    Returns:
        Window: The configured phone input window.
    """
    return Window(
        Format(
            "Введите телефон организации (или нажмите 'Пропустить'):",
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        Format(
            "Введите новый телефон организации (или нажмите 'Пропустить'):",
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
                id="back_org_phone_inputedit_window",
                state=OrganizationDialog.edit_menu,
                when="is_editing",
            ),
            Back(
                Const("Назад"),
                when=lambda data, widget, manager: not data.get("is_editing", False),
            ),
        ),
        state=OrganizationDialog.phone_input,
        getter=get_organization_form_data,
    )


def select_organization_to_edit_window():
    """Create organization selection window for editing.

    Returns:
        Window: The configured organization selection window.
    """
    return Window(
        Format("Выберите организацию для редактирования:"),
        ScrollingGroup(
            Select(
                Format("{item.name} ({item.code})"),
                item_id_getter=lambda org: org.id,
                items="organizations",
                id="select_organization_to_edit",
                on_click=on_select_organization_to_edit,
            ),
            id="scrolling_organizations",
            width=1,
            height=10,
            when="has_organizations",
        ),
        Cancel(
            Const("Назад"),
            id="back_select_organization_to_edit_window",
        ),
        state=OrganizationDialog.select_organization_to_edit,
        getter=get_organizations_list_data,
    )


def edit_menu_window():
    """Create edit menu window for existing organization.

    Returns:
        Window: The configured edit menu window.
    """
    return Window(
        Format(
            "Редактирование организации:\n\n"
            "Название: {name}\n"
            "Код: {code}\n"
            "Адрес: {address}\n"
            "Телефон: {phone}\n\n"
            "Что вы хотите изменить?"
        ),
        Row(
            Button(
                text=Const("Изменить название ✏️"),
                id="edit_name",
                on_click=on_edit_organization_name,
            ),
        ),
        Row(
            Button(
                text=Const("Изменить код 🔤"),
                id="edit_code",
                on_click=on_edit_organization_code,
            ),
        ),
        Row(
            Button(
                text=Const("Изменить адрес 📍"),
                id="edit_address",
                on_click=on_edit_organization_address,
            ),
        ),
        Row(
            Button(
                text=Const("Изменить телефон 📞"),
                id="edit_phone",
                on_click=on_edit_organization_phone,
            ),
        ),
        Row(
            Button(
                text=Const("Управление сотрудниками 👥"),
                id="manage_employees",
                on_click=on_manage_employees,
            ),
        ),
        Row(
            Button(
                text=Const("Сохранить изменения ✅"),
                id="save_changes",
                on_click=on_save_organization_changes,
            ),
        ),
        Back(
            Const("Назад"),
            id="back_org_edit_menu_window",
        ),
        state=OrganizationDialog.edit_menu,
        getter=get_organization_form_data,
    )


def manage_employees_window():
    """Create employees management window.

    Returns:
        Window: The configured employees management window.
    """
    return Window(
        # Show different message for first creation
        Format(
            "🎉 Отлично! Организация создана.\n\n"
            "Теперь вы можете добавить сотрудников в вашу организацию. "
            "Вы можете пригласить их по ссылке или создать сотрудника вручную.\n\n"
            "Выберите действие:",
            when="is_first_creation",
        ),
        Format(
            "Управление сотрудниками:\n\nВыберите сотрудника:",
            when=lambda data, widget, manager: not data.get("is_first_creation", False),
        ),
        ScrollingGroup(
            Select(
                Format("{item[display]}"),
                item_id_getter=lambda emp: str(emp["id"]),
                items="active_employees",
                id="fire_employee",
                on_click=on_fire_employee,
            ),
            Select(
                Format("{item[display]}"),
                item_id_getter=lambda emp: str(emp["id"]),
                items="fired_employees",
                id="restore_employee",
                on_click=on_restore_employee,
            ),
            id="scrolling_employees",
            width=1,
            height=10,
            when="has_employees",
        ),
        Format(
            "Нет сотрудников в организации.",
            when=lambda data, widget, manager: not data.get("has_employees", False),
        ),
        Row(
            SwitchTo(
                Const("Пригласить сотрудника ➕"),
                id="invite_employee",
                state=OrganizationDialog.invite_employee,
            ),
        ),
        # Show "Continue" button for first creation, "Back" for regular management
        Button(
            Const("Продолжить ➡️"),
            id="continue_to_main_menu",
            on_click=on_continue_to_main_menu,
            when="is_first_creation",
        ),
        SwitchTo(
            Const("Назад"),
            id="back_org_phone_inputedit_window",
            state=OrganizationDialog.edit_menu,
            when=lambda data, widget, manager: not data.get("is_first_creation", False),
        ),
        state=OrganizationDialog.manage_employees,
        getter=get_employees_list_data_for_management,
    )


def invite_employee_window():
    """Create invite employee window.

    Returns:
        Window: The configured invite employee window.
    """
    return Window(
        Format(
            "Приглашение сотрудника\n\n"
            "Ссылка для приглашения:\n"
            "{invitation_link}\n\n"
            "Отправьте эту ссылку сотруднику. "
            "Ссылка действительна в течение 7 дней и может быть использована только один раз."
        ),
        Row(
            Button(
                Const("Создать новую ссылку 🔄"),
                id="regenerate_invitation",
                on_click=on_invite_employee,
            ),
        ),
        # Show "Continue" button for first creation, "Back" for regular management
        Button(
            Const("Продолжить ➡️"),
            id="continue_to_main_menu",
            on_click=on_continue_to_main_menu,
            when="is_first_creation",
        ),
        SwitchTo(
            Const("Назад"),
            id="back_to_manage_employees",
            state=OrganizationDialog.manage_employees,
            when=lambda data, widget, manager: not data.get("is_first_creation", False),
        ),
        state=OrganizationDialog.invite_employee,
        getter=get_invitation_data,
    )


def confirm_window():
    """Create confirm window.

    Returns:
        Window: The configured confirm window.
    """
    return Window(
        Format(
            "Проверьте данные организации:\n\n"
            "Название: {name}\n"
            "Код: {code}\n"
            "Адрес: {address}\n"
            "Телефон: {phone}\n\n"
            "Всё верно?",
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        Format(
            "Проверьте изменения организации:\n\n"
            "Название: {name}\n"
            "Код: {code}\n"
            "Адрес: {address}\n"
            "Телефон: {phone}\n\n"
            "Сохранить изменения?",
            when="is_editing",
        ),
        Row(
            Button(
                text=Const("Подтвердить ✅"),
                id="confirm",
                on_click=on_confirm_organization,
            ),
            SwitchTo(
                Const("Назад"),
                id="back_org_confirm_window",
                state=OrganizationDialog.edit_menu,
                when="is_editing",
            ),
            SwitchTo(
                Const("Назад"),
                id="back_org_confirm_create_window",
                state=OrganizationDialog.phone_input,
                when=lambda data, widget, manager: not data.get("is_editing", False),
            ),
        ),
        state=OrganizationDialog.confirm,
        getter=get_organization_form_data,
    )
