"""States for greeting dialog."""

from aiogram.fsm.state import State, StatesGroup


class GreetingDialog(StatesGroup):
    """States for greeting dialog.

    Flow (matches the design diagram):
      /start → greeting (main menu)
        ├── admin_panel        (admin/superuser branch)
        │     ├── organizations_menu
        │     ├── employees_menu
        │     ├── criteria_and_sets_menu
        │     ├── evaluations_admin_menu
        │     └── (analytics → separate dialog)
        ├── my_menu            (all users branch)
        │     ├── my_evaluations
        │     └── available_evaluations
        ├── invite_admin       (superuser only)
        ├── invite_to_org      (admin/manager)
        └── switch_organization (superuser only)
    """

    greeting = State()

    # Admin panel (left branch on diagram)
    admin_panel = State()
    organizations_menu = State()
    employees_menu = State()
    criteria_and_sets_menu = State()
    evaluations_admin_menu = State()

    # My menu (right branch on diagram)
    my_menu = State()
    my_evaluations = State()

    # Invitations
    invite_admin = State()
    select_invite_role = State()  # Choose role before generating invite link
    invite_to_org = State()

    # Organization switching (superuser)
    switch_organization = State()
