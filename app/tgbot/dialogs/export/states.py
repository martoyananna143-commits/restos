"""States for export dialog."""

from aiogram.fsm.state import State, StatesGroup


class ExportDialog(StatesGroup):
    """States for export dialog."""

    select_format = State()  # Выбор формата экспорта (PDF/Excel)
