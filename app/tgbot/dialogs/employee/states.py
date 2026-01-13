"""States for employee dialog."""

from aiogram.fsm.state import State, StatesGroup


class EmployeeDialog(StatesGroup):
    """States for employee creation dialog."""

    select_organization = State()
    select_organization_for_edit = State()  # Выбор организации для редактирования сотрудника
    select_employee_to_edit = State()  # Выбор сотрудника для редактирования
    edit_menu = State()  # Меню редактирования существующего сотрудника
    full_name_input = State()
    position_input = State()
    phone_input = State()
    confirm = State()
    add_more = State()

