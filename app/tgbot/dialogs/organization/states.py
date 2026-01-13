"""States for organization dialog."""

from aiogram.fsm.state import State, StatesGroup


class OrganizationDialog(StatesGroup):
    """States for organization creation dialog."""

    check_organization = State()
    select_organization_to_edit = State()  # Выбор организации для редактирования
    edit_menu = State()  # Меню редактирования существующей организации
    manage_employees = State()  # Управление сотрудниками организации
    invite_employee = State()  # Приглашение сотрудника
    name_input = State()
    code_input = State()
    address_input = State()
    phone_input = State()
    confirm = State()
