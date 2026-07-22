"""Getters for criterion set dialog."""

from dependency_injector.wiring import Provide, inject

from aiogram_dialog import DialogManager

from app.internal import Container
from app.internal.services.criterion_service import CriterionService
from app.internal.services.criterion_set_service import CriterionSetService
from app.tgbot.dialogs.common.utils import get_form_value


@inject
async def get_criterion_sets_list_data(
    dialog_manager: DialogManager,
    criterion_set_service: CriterionSetService = Provide[Container.criterion_set_service],
    *args,
    **kwargs,
):
    """Get data for criterion sets list window.

    Args:
        dialog_manager: Dialog manager instance.
        criterion_set_service: CriterionSet service instance (injected).
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with criterion sets list data.
    """
    organization_id = dialog_manager.dialog_data.get("organization_id")
    # Если organization_id не найден в dialog_data, проверяем middleware_data
    if not organization_id:
        organization = dialog_manager.middleware_data.get("organization")
        if organization:
            organization_id = organization.id
            # Устанавливаем organization_id в dialog_data для последующих вызовов
            dialog_manager.dialog_data["organization_id"] = organization_id
        else:
            # Проверяем preset_organization_id в middleware_data
            preset_org_id = dialog_manager.middleware_data.get("preset_organization_id")
            if preset_org_id:
                organization_id = preset_org_id
                dialog_manager.dialog_data["organization_id"] = organization_id
    
    if not organization_id:
        return {
            "criterion_sets": [],
            "has_criterion_sets": False,
            "no_criterion_sets": True,
        }
    
    criterion_sets = await criterion_set_service.get_by_organization_id(organization_id)
    
    # Добавляем текст для отображения дефолтного статуса
    criterion_sets_with_display = []
    for cs in criterion_sets:
        cs_dict = {
            "id": cs.id,
            "name": cs.name,
            "description": cs.description,
            "is_default": cs.is_default,
            "display_name": f"{cs.name} (Дефолтный)" if cs.is_default else cs.name,
        }
        criterion_sets_with_display.append(cs_dict)
    
    return {
        "criterion_sets": criterion_sets_with_display,
        "has_criterion_sets": len(criterion_sets) > 0,
        "no_criterion_sets": len(criterion_sets) == 0,
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
    # Если organization_id не найден в dialog_data, проверяем middleware_data
    if not organization_id:
        organization = dialog_manager.middleware_data.get("organization")
        if organization:
            organization_id = organization.id
            # Устанавливаем organization_id в dialog_data для последующих вызовов
            dialog_manager.dialog_data["organization_id"] = organization_id
        else:
            # Проверяем preset_organization_id в middleware_data
            preset_org_id = dialog_manager.middleware_data.get("preset_organization_id")
            if preset_org_id:
                organization_id = preset_org_id
                dialog_manager.dialog_data["organization_id"] = organization_id
    
    if not organization_id:
        return {
            "criteria": [],
            "has_criteria": False,
            "no_criteria": True,
            "criteria_count": 0,
        }
    
    criteria = await criterion_service.get_by_organization_id(organization_id)
    
    # Получаем уже выбранные критерии
    selected_criterion_ids = dialog_manager.dialog_data.get("selected_criterion_ids", [])
    
    # Добавляем маркер выбора для каждого критерия
    criteria_with_markers = []
    for criterion in criteria:
        criterion_dict = {
            "id": criterion.id,
            "name": criterion.name,
            "code": criterion.code,
            "selected_marker": "✓ " if criterion.id in selected_criterion_ids else "◻ ",
        }
        criteria_with_markers.append(criterion_dict)
    
    is_editing = bool(dialog_manager.dialog_data.get("criterion_set_id"))
    
    return {
        "criteria": criteria_with_markers,
        "has_criteria": len(criteria) > 0,
        "no_criteria": len(criteria) == 0,
        "selected_criterion_ids": selected_criterion_ids,
        "criteria_count": len(selected_criterion_ids),
        "is_editing": is_editing,
    }


async def get_criterion_set_form_data(
    dialog_manager: DialogManager,
    *args,
    **kwargs,
):
    """Get data for criterion set form window.

    Args:
        dialog_manager: Dialog manager instance.
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with criterion set form data.
    """
    data = dialog_manager.dialog_data
    selected_criterion_ids = data.get("selected_criterion_ids", [])
    is_default = data.get("is_default", False)
    is_editing = bool(data.get("criterion_set_id"))
    
    return {
        "name": get_form_value(data, "name", ""),
        "description": get_form_value(data, "description", "Не указано"),
        "is_default": is_default,
        "is_default_text": "Да" if is_default else "Нет",
        "current_default_text": "Дефолтный" if is_default else "Не дефолтный",
        "criteria_count": len(selected_criterion_ids),
        "is_editing": is_editing,
    }

