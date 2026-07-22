"""Employee models."""

from app.infra.database.models.employee.employee import Employee
from app.infra.database.models.employee.employee_type import EmployeeType

__all__ = [
    "EmployeeType",
    "Employee",
]
