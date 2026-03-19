"""Windows for greeting dialog.

Implements the main navigation flow from the design diagram:
  greeting → admin_panel / my_menu (split by role)
"""

from aiogram_dialog import Window
from aiogram_dialog.widgets.kbd import Button, Row, ScrollingGroup, Select, SwitchTo
from aiogram_dialog.widgets.text import Const, Format

from app.tgbot.dialogs.greeting.getters import (
    get_admin_invitation_data,
    get_employees_menu_data,
    get_greeting_data,
    get_org_invitation_data,
    get_switch_organization_data,
)
from app.tgbot.dialogs.greeting.handlers import (
    on_create_criterion_clicked,
    on_create_criterion_set_clicked,
    on_create_employee_clicked,
    on_create_evaluation_clicked,
    on_delete_evaluation_clicked,
    on_edit_employee_clicked,
    on_help_clicked,
    on_invite_admin,
    on_invite_to_org,
    on_open_analytics_webapp,
    on_open_employees_webapp,
    on_open_my_evaluations_webapp,
    on_open_objects_analytics,
    on_select_invite_role,
    on_switch_organization_selected,
)
from app.tgbot.dialogs.greeting.states import GreetingDialog


# =============================================================================
# 1. GREETING — Main entry point (top of diagram)
# =============================================================================

def greeting_window():
    """Main menu: two branches (admin panel / my menu) + invitations."""
    return Window(
        Format("{greeting_text}"),
        # --- Two main branches ---
        Row(
            SwitchTo(
                text=Const("Панель администратора 🛠"),
                id="admin_panel_btn",
                state=GreetingDialog.admin_panel,
                when="is_administrator",
            ),
        ),
        Row(
            SwitchTo(
                text=Const("Моё меню 📂"),
                id="my_menu_btn",
                state=GreetingDialog.my_menu,
            ),
        ),
        # --- Invite (manager/admin/superuser) ---
        Row(
            Button(
                text=Const("Пригласить в организацию 🔗"),
                id="invite_to_org_btn",
                on_click=on_invite_to_org,
                when="can_invite_to_org",
            ),
        ),
        Row(
            Button(
                text=Const("Пригласить администратора 👑"),
                id="invite_admin_btn",
                on_click=on_invite_admin,
                when="is_superuser",
            ),
        ),
        # --- Switch org (superuser only) ---
        Row(
            SwitchTo(
                text=Const("Переключить организацию 🔄"),
                id="switch_org_btn",
                state=GreetingDialog.switch_organization,
                when="is_superuser",
            ),
        ),
        # --- Help ---
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


# =============================================================================
# 2. ADMIN PANEL (left branch on diagram: "Панель администратора")
# =============================================================================

def admin_panel_window():
    """Admin panel hub — links to sub-sections."""
    return Window(
        Const("Панель администратора 🛠\n\nВыберите раздел:"),
        Row(
            SwitchTo(
                text=Const("Настройка критериев 📋"),
                id="criteria_and_sets_menu",
                state=GreetingDialog.criteria_and_sets_menu,
            ),
        ),
        Row(
            SwitchTo(
                text=Const("Управление сотрудниками 👥"),
                id="employees_menu",
                state=GreetingDialog.employees_menu,
            ),
        ),
        Row(
            SwitchTo(
                text=Const("Организации 🏢"),
                id="organizations_menu",
                state=GreetingDialog.organizations_menu,
            ),
        ),
        Row(
            SwitchTo(
                text=Const("Замеры (создать / удалить) 📊"),
                id="evaluations_admin_menu",
                state=GreetingDialog.evaluations_admin_menu,
            ),
        ),
        Row(
            Button(
                text=Const("📈 Аналитика (Mini App)"),
                id="analytics_webapp_btn",
                on_click=on_open_analytics_webapp,
            ),
        ),
        Row(
            Button(
                text=Const("📦 Объекты и отчёты"),
                id="objects_analytics_btn",
                on_click=on_open_objects_analytics,
            ),
        ),
        SwitchTo(
            text=Const("Назад ⬅️"),
            id="back_to_greeting_from_admin",
            state=GreetingDialog.greeting,
        ),
        state=GreetingDialog.admin_panel,
    )



# =============================================================================
# 3. MY MENU (right branch on diagram: "Моё меню")
# =============================================================================

def my_menu_window():
    """User menu — available evaluations and history."""
    return Window(
        Const("Моё меню 📂\n\nВыберите действие:"),
        Row(
            SwitchTo(
                text=Const("Мои замеры 📁"),
                id="my_evaluations_btn",
                state=GreetingDialog.my_evaluations,
            ),
        ),
        Row(
            Button(
                text=Const("Пройти замер 📝"),
                id="available_evaluations_btn",
                on_click=on_create_evaluation_clicked,
                when="can_make_evaluation",
            ),
        ),
        SwitchTo(
            text=Const("Назад ⬅️"),
            id="back_to_greeting_from_my",
            state=GreetingDialog.greeting,
        ),
        state=GreetingDialog.my_menu,
        getter=get_greeting_data,
    )


# =============================================================================
# 4. Sub-sections of ADMIN PANEL
# =============================================================================

def organizations_menu_window():
    """Organizations management menu."""
    return Window(
        Const("Управление организациями:\n\nВыберите действие:"),
        Button(
            text=Const("Создать организацию ➕"),
            id="create_organization",
            on_click=_on_create_org_clicked,
            when="is_superuser",
        ),
        Button(
            text=Const("Редактировать организацию ✏️"),
            id="edit_organization",
            on_click=_on_edit_org_clicked,
        ),
        SwitchTo(
            text=Const("Назад ⬅️"),
            id="back_to_admin_panel_from_org",
            state=GreetingDialog.admin_panel,
        ),
        state=GreetingDialog.organizations_menu,
        getter=get_greeting_data,
    )


async def _on_create_org_clicked(callback, button, dialog_manager):
    from app.tgbot.dialogs.organization.states import OrganizationDialog
    await dialog_manager.start(OrganizationDialog.name_input)


async def _on_edit_org_clicked(callback, button, dialog_manager):
    from app.tgbot.dialogs.organization.states import OrganizationDialog
    await dialog_manager.start(OrganizationDialog.select_organization_to_edit)


def employees_menu_window():
    """Employees management menu with WebApp option."""
    return Window(
        Const("Управление сотрудниками 👥\n\nВыберите действие:"),
        Row(
            Button(
                text=Const("📱 Открыть список (Mini App)"),
                id="open_employees_webapp",
                on_click=on_open_employees_webapp,
            ),
        ),
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
            text=Const("Назад ⬅️"),
            id="back_to_admin_panel_from_emp",
            state=GreetingDialog.admin_panel,
        ),
        state=GreetingDialog.employees_menu,
        getter=get_employees_menu_data,
    )


def criteria_and_sets_menu_window():
    """Criteria and sets management menu."""
    return Window(
        Const("Настройка критериев и наборов\n\nВыберите действие:"),
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
            text=Const("Назад ⬅️"),
            id="back_to_admin_panel_from_crit",
            state=GreetingDialog.admin_panel,
        ),
        state=GreetingDialog.criteria_and_sets_menu,
    )


def evaluations_admin_menu_window():
    """Admin: create / delete evaluations."""
    return Window(
        Const("Управление замерами:\n\nВыберите действие:"),
        Row(
            Button(
                text=Const("Сделать замер 📊"),
                id="create_evaluation",
                on_click=on_create_evaluation_clicked,
            ),
        ),
        Row(
            Button(
                text=Const("Удалить замер 🗑️"),
                id="delete_evaluation",
                on_click=on_delete_evaluation_clicked,
            ),
        ),
        SwitchTo(
            text=Const("Назад ⬅️"),
            id="back_to_admin_panel_from_eval",
            state=GreetingDialog.admin_panel,
        ),
        state=GreetingDialog.evaluations_admin_menu,
        getter=get_greeting_data,
    )


# =============================================================================
# 5. Sub-sections of MY MENU
# =============================================================================

def my_evaluations_window():
    """View evaluations — opens Mini Web App for rich UI."""
    return Window(
        Const(
            "Мои замеры 📁\n\n"
            "Нажмите кнопку ниже, чтобы открыть подробный список "
            "ваших замеров в удобном формате."
        ),
        Row(
            Button(
                text=Const("📁 Открыть мои замеры"),
                id="open_my_evals_webapp",
                on_click=on_open_my_evaluations_webapp,
            ),
        ),
        SwitchTo(
            Const("Назад ⬅️"),
            id="back_to_my_menu_from_evals",
            state=GreetingDialog.my_menu,
        ),
        state=GreetingDialog.my_evaluations,
    )



# =============================================================================
# 6. INVITATIONS
# =============================================================================

def invite_admin_window():
    """Invite bot administrator (superuser only)."""
    return Window(
        Format(
            "Приглашение администратора 👑\n\n"
            "Ссылка для приглашения:\n"
            "{invitation_link}\n\n"
            "Приглашённый получит статус администратора и сможет создать свою организацию.\n"
            "Ссылка действительна 7 дней, однократного использования."
        ),
        Row(
            Button(
                Const("Создать новую ссылку 🔄"),
                id="regenerate_admin_invitation",
                on_click=on_invite_admin,
            ),
        ),
        SwitchTo(
            Const("Назад ⬅️"),
            id="back_to_greeting_from_inv_admin",
            state=GreetingDialog.greeting,
        ),
        state=GreetingDialog.invite_admin,
        getter=get_admin_invitation_data,
    )


def select_invite_role_window():
    """Choose which role the invited person will receive."""
    return Window(
        Const(
            "Пригласить в организацию 🔗\n\n"
            "Выберите роль для приглашённого:"
        ),
        Select(
            Format("{item[display]}"),
            item_id_getter=lambda role: role["id"],
            items="invite_roles",
            id="select_invite_role",
            on_click=on_select_invite_role,
        ),
        SwitchTo(
            Const("Назад ⬅️"),
            id="back_to_greeting_from_role_select",
            state=GreetingDialog.greeting,
        ),
        state=GreetingDialog.select_invite_role,
        getter=_get_invite_roles_data,
    )


async def _get_invite_roles_data(dialog_manager, *args, **kwargs):
    """Return available roles for the invite role selection window."""
    from app.tgbot.dialogs.greeting.handlers import INVITE_ROLE_MAP

    roles = [
        {"id": key, "display": f"{role['name']}"}
        for key, role in INVITE_ROLE_MAP.items()
    ]
    return {"invite_roles": roles}


def invite_to_org_window():
    """Invite employee to current organisation (superuser / admin / manager)."""
    return Window(
        Format(
            "Пригласить в организацию 🔗\n\n"
            "Организация: {organization_name}\n"
            "Роль: {invite_role_name}\n\n"
            "Ссылка для приглашения:\n"
            "{invitation_link}\n\n"
            "Пользователь присоединится к вашей организации с выбранной ролью.\n"
            "Ссылка действительна 7 дней, однократного использования."
        ),
        Row(
            SwitchTo(
                Const("Пригласить с другой ролью 🔄"),
                id="change_invite_role",
                state=GreetingDialog.select_invite_role,
            ),
        ),
        SwitchTo(
            Const("Назад ⬅️"),
            id="back_to_greeting_from_inv_org",
            state=GreetingDialog.greeting,
        ),
        state=GreetingDialog.invite_to_org,
        getter=get_org_invitation_data,
    )


# =============================================================================
# 7. SWITCH ORGANIZATION (superuser only)
# =============================================================================

def switch_organization_window():
    """Select active organization (superuser only)."""
    return Window(
        Const("Переключить организацию 🔄\n\nВыберите организацию:"),
        ScrollingGroup(
            Select(
                Format("{item.name}"),
                item_id_getter=lambda org: org.id,
                items="organizations",
                id="select_org_switch",
                on_click=on_switch_organization_selected,
            ),
            id="scrolling_switch_org",
            width=1,
            height=10,
            when="has_organizations",
            hide_on_single_page=True,
        ),
        Format("У вас нет организаций.", when="no_organizations"),
        SwitchTo(
            Const("Назад ⬅️"),
            id="back_to_greeting_from_switch",
            state=GreetingDialog.greeting,
        ),
        state=GreetingDialog.switch_organization,
        getter=get_switch_organization_data,
    )
