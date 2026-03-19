"""States for employee dialog."""

from aiogram.fsm.state import State, StatesGroup


class EmployeeDialog(StatesGroup):
    """States for employee creation dialog."""

    select_organization = State()
    select_organization_for_edit = State()
    select_employee_to_edit = State()
    edit_menu = State()
    full_name_input = State()
    position_input = State()
    phone_input = State()
    select_role = State()  # Select employee_type (role) for employee
    confirm = State()
    add_more = State()

