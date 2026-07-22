"""Getters for criterion dialog."""

from aiogram_dialog import DialogManager
from dependency_injector.wiring import Provide, inject

from app.internal import Container
from app.internal.services.criterion_service import CriterionService
from app.tgbot.dialogs.common.utils import get_form_value


async def is_editing(
    dialog_manager: DialogManager,
    *args,
    **kwargs,
):
    return {
        "is_editing": bool(dialog_manager.dialog_data.get("criterion_id")),
    }


async def get_criterion_form_data(
    dialog_manager: DialogManager,
    *args,
    **kwargs,
):
    """Get data for criterion form window.

    Args:
        dialog_manager: Dialog manager instance.
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with criterion form data.
    """
    data = dialog_manager.dialog_data
    is_editing = bool(data.get("criterion_id"))
    value_type = data.get("value_type", "boolean")
    is_required = data.get("is_required", True)

    value_type_names = {
        "boolean": "Да/Нет",
        "string": "Текст",
        "number": "Число",
    }
    value_type_name = value_type_names.get(value_type, value_type)
    is_required_name = "Да" if is_required else "Нет"

    return {
        "name": get_form_value(data, "name", ""),
        "code": get_form_value(data, "code", ""),
        "description": get_form_value(data, "description", "Не указано"),
        "value_type": value_type,
        "value_type_name": value_type_name,
        "is_required": is_required,
        "is_required_name": is_required_name,
        "is_editing": is_editing,
    }


@inject
async def get_criteria_list_data(
    dialog_manager: DialogManager,
    criterion_service: CriterionService = Provide[Container.criterion_service],
    *args,
    **kwargs,
):
    """Get data for criteria list window.

    Args:
        dialog_manager: Dialog manager instance.
        criterion_service: Criterion service instance (injected).
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with criteria list data.
    """
    organization_id = dialog_manager.dialog_data.get("organization_id")
    if not organization_id:
        org = dialog_manager.middleware_data.get("organization")
        if org:
            organization_id = org.id
            dialog_manager.dialog_data["organization_id"] = organization_id
    if not organization_id:
        return {
            "criteria": [],
            "has_criteria": False,
            "no_criteria": True,
        }

    criteria = await criterion_service.get_by_organization_id(organization_id)

    # Формируем список для отображения
    criteria_with_display = []
    for criterion in criteria:
        criteria_with_display.append(
            {
                "id": criterion.id,
                "name": criterion.name,
                "code": criterion.code,
                "description": criterion.description,
                "display_name": f"{criterion.name} ({criterion.code})",
            }
        )

    return {
        "criteria": criteria_with_display,
        "has_criteria": len(criteria) > 0,
        "no_criteria": len(criteria) == 0,
    }


