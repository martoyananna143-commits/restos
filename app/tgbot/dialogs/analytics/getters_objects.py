"""Getters for objects section in analytics dialog."""

import logging

from aiogram_dialog import DialogManager
from dependency_injector.wiring import Provide, inject

from app.internal import Container
from app.internal.services.analytics_service import AnalyticsService
from app.internal.services.criterion_service import CriterionService
from app.internal.services.criterion_set_service import CriterionSetService
from app.internal.services.employee_service import EmployeeService
from app.internal.services.organization_service import OrganizationService
from app.internal.services.presentation_percent import format_percent

logger = logging.getLogger(__name__)


async def get_objects_type_data(
    dialog_manager: DialogManager,
    *args,
    **kwargs,
):
    """Get data for object type selection window.

    Args:
        dialog_manager: Dialog manager instance.
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with object types data.
    """
    return {
        "object_types": [
            {
                "id": "employees",
                "name": "👥 Сотрудники",
                "description": "Просмотр и экспорт сотрудников",
            },
            {
                "id": "evaluations",
                "name": "📊 Замеры",
                "description": "Просмотр и экспорт замеров",
            },
            {
                "id": "criteria",
                "name": "📋 Критерии",
                "description": "Просмотр и экспорт критериев",
            },
            {
                "id": "criterion_sets",
                "name": "📦 Наборы критериев",
                "description": "Просмотр и экспорт наборов критериев",
            },
        ],
    }


@inject
async def get_objects_list_data(
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
    analytics_service: AnalyticsService = Provide[Container.analytics_service],
    criterion_service: CriterionService = Provide[Container.criterion_service],
    criterion_set_service: CriterionSetService = Provide[
        Container.criterion_set_service
    ],
    *args,
    **kwargs,
):
    """Get paginated list of objects.

    Args:
        dialog_manager: Dialog manager instance.
        employee_service: Employee service instance (injected).
        organization_service: Organization service instance (injected).
        analytics_service: Analytics service instance (injected).
        criterion_service: Criterion service instance (injected).
        criterion_set_service: Criterion set service instance (injected).
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with paginated objects list data.
    """
    organization_id = dialog_manager.dialog_data.get("organization_id")
    if not organization_id:
        org = dialog_manager.middleware_data.get("organization")
        if org:
            organization_id = org.id
            dialog_manager.dialog_data["organization_id"] = organization_id
    object_type = dialog_manager.dialog_data.get("object_type")
    current_page = dialog_manager.dialog_data.get("objects_page", 0)
    items_per_page = 5

    if not organization_id:
        return {
            "objects": [],
            "display_text": "❌ Организация не выбрана.",
            "has_prev": False,
            "has_next": False,
            "current_page": 0,
            "total_pages": 0,
            "object_type": object_type,
        }

    if not object_type:
        return {
            "objects": [],
            "display_text": "❌ Тип объекта не выбран.",
            "has_prev": False,
            "has_next": False,
            "current_page": 0,
            "total_pages": 0,
            "object_type": object_type,
        }

    try:
        objects_list = []
        object_type_name = ""

        # Поддерживаем как единственное, так и множественное число
        if object_type in ("employees", "employee"):
            employees = await employee_service.get_by_organization_id(organization_id)
            object_type_name = "Сотрудники"
            for emp in employees:
                objects_list.append(
                    {
                        "id": emp.id,
                        "name": emp.full_name,
                        "type": "employee",
                        "display_text": f"👤 <b>{emp.full_name}</b>\n   ID: {emp.id} | Должность: {emp.position or 'Не указана'}",
                    }
                )

        elif object_type in ("evaluations", "evaluation"):
            evaluations_data = (
                await analytics_service.evaluation_repository.get_analytics_data(
                    organization_id=organization_id,
                    criterion_ids=None,
                    employee_ids=None,
                    date_from=None,
                    date_to=None,
                    evaluation_type_id=None,
                )
            )
            object_type_name = "Замеры"
            # Получаем уникальные замеры (убираем дубликаты от JOIN)
            seen_ids = set()
            for eval_data in evaluations_data:
                eval_id = eval_data.get("id")
                if eval_id and eval_id not in seen_ids:
                    seen_ids.add(eval_id)
                    eval_date = eval_data.get("evaluation_date")
                    score = eval_data.get("score_percentage", 0.0)
                    date_str = (
                        eval_date.strftime("%Y-%m-%d %H:%M") if eval_date else "N/A"
                    )
                    objects_list.append(
                        {
                            "id": eval_id,
                            "name": f"Замер #{eval_id}",
                            "type": "evaluation",
                            "display_text": f"📊 Замер #{eval_id}\n   Дата: {date_str} | Балл: {format_percent(score)}",
                        }
                    )

        elif object_type in ("criteria", "criterion"):
            criteria = await criterion_service.get_by_organization_id(organization_id)
            object_type_name = "Критерии"
            for criterion in criteria:
                objects_list.append(
                    {
                        "id": criterion.id,
                        "name": criterion.name,
                        "type": "criterion",
                        "display_text": f"📋 <b>{criterion.name}</b>\n   ID: {criterion.id} | Код: {criterion.code} | Тип: {criterion.value_type}",
                    }
                )

        elif object_type in ("criterion_sets", "criterion_set"):
            criterion_sets = await criterion_set_service.get_by_organization_id(
                organization_id
            )
            object_type_name = "Наборы критериев"
            for cs in criterion_sets:
                default_marker = " (Дефолтный)" if cs.is_default else ""
                objects_list.append(
                    {
                        "id": cs.id,
                        "name": cs.name,
                        "type": "criterion_set",
                        "display_text": f"📦 <b>{cs.name}{default_marker}</b>\n   ID: {cs.id} | Описание: {cs.description or 'Нет'}",
                    }
                )

        # Пагинация
        total_items = len(objects_list)
        total_pages = (
            (total_items + items_per_page - 1) // items_per_page
            if total_items > 0
            else 1
        )

        if current_page >= total_pages:
            current_page = max(0, total_pages - 1)
            dialog_manager.dialog_data["objects_page"] = current_page

        start_idx = current_page * items_per_page
        end_idx = start_idx + items_per_page
        page_objects = objects_list[start_idx:end_idx]

        header_lines = [
            f"📦 <b>{object_type_name}</b>",
            f"Страница {current_page + 1} из {total_pages}",
            f"Всего объектов: {total_items}",
            "──────────────────────────────",
        ]

        if page_objects:
            object_lines = [obj["display_text"] for obj in page_objects]
        else:
            object_lines = ["Нет данных для отображения"]

        # Объединяем: одинарные переносы в заголовке, двойной перед объектами, одинарные между объектами
        display_text = "\n".join(header_lines) + "\n" + "\n".join(object_lines)

        return {
            "objects": page_objects,
            "display_text": display_text,
            "has_prev": current_page > 0,
            "has_next": current_page < total_pages - 1,
            "has_objects": len(page_objects) > 0,
            "current_page": current_page,
            "total_pages": total_pages,
            "object_type": object_type,
            "object_type_name": object_type_name,
        }

    except Exception as e:
        logger.error(f"Error loading objects list: {e}", exc_info=True)
        return {
            "objects": [],
            "display_text": f"❌ Ошибка при загрузке данных: {str(e)}",
            "has_prev": False,
            "has_next": False,
            "current_page": 0,
            "total_pages": 0,
            "object_type": object_type,
        }


@inject
async def get_object_detail_data(
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
    analytics_service: AnalyticsService = Provide[Container.analytics_service],
    criterion_service: CriterionService = Provide[Container.criterion_service],
    criterion_set_service: CriterionSetService = Provide[
        Container.criterion_set_service
    ],
    *args,
    **kwargs,
):
    """Get detailed data for a specific object.

    Args:
        dialog_manager: Dialog manager instance.
        employee_service: Employee service instance (injected).
        organization_service: Organization service instance (injected).
        analytics_service: Analytics service instance (injected).
        criterion_service: Criterion service instance (injected).
        criterion_set_service: Criterion set service instance (injected).
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with object detail data.
    """
    organization_id = dialog_manager.dialog_data.get("organization_id")
    object_type = dialog_manager.dialog_data.get("object_type")
    object_id = dialog_manager.dialog_data.get("selected_object_id")

    if not object_id:
        return {
            "detail_text": "❌ Объект не выбран.",
            "object_type": object_type,
            "object_id": None,
        }

    try:
        detail_lines = []

        if not object_type:
            return {
                "detail_text": "❌ Тип объекта не указан.",
                "object_type": object_type,
                "object_id": object_id,
            }

        # Проверяем тип объекта (может быть как единственное, так и множественное число)
        if object_type in ("employees", "employee"):
            employee = await employee_service.get_by_id(object_id)
            if not employee:
                return {
                    "detail_text": f"❌ Сотрудник с ID {object_id} не найден.",
                    "object_type": object_type,
                    "object_id": object_id,
                }

            detail_lines.extend(
                [
                    f"👤 <b>Сотрудник: {employee.full_name}</b>",
                    "",
                    f"ID: {employee.id}",
                    f"Должность: {employee.position or 'Не указана'}",
                    f"Телефон: {employee.phone or 'Не указан'}",
                    f"Telegram ID: {employee.telegram_id or 'Не указан'}",
                    f"Username: {employee.username or 'Не указан'}",
                    f"Дата найма: {employee.hire_date.strftime('%Y-%m-%d') if employee.hire_date else 'Не указана'}",
                    f"Активен: {'Да' if employee.is_active else 'Нет'}",
                ]
            )

            # Получаем замеры сотрудника
            evaluations_data = (
                await analytics_service.evaluation_repository.get_analytics_data(
                    organization_id=organization_id,
                    criterion_ids=None,
                    employee_ids=[object_id],
                    date_from=None,
                    date_to=None,
                    evaluation_type_id=None,
                )
            )

            seen_ids = set()
            eval_count = 0
            scores = []
            last_eval_date = None
            for eval_data in evaluations_data:
                eval_id = eval_data.get("id")
                if eval_id and eval_id not in seen_ids:
                    seen_ids.add(eval_id)
                    eval_count += 1
                    score = eval_data.get("score_percentage", 0.0)
                    if score is not None:
                        scores.append(score)
                    eval_date = eval_data.get("evaluation_date")
                    if eval_date and (not last_eval_date or eval_date > last_eval_date):
                        last_eval_date = eval_date

            detail_lines.extend(
                [
                    "",
                    "<b>Статистика:</b>",
                    f"Замеров: {eval_count}",
                ]
            )

            if scores:
                avg_score = sum(scores) / len(scores)
                detail_lines.append(f"Средний балл: {format_percent(avg_score)}")
                detail_lines.append(f"Лучший результат: {format_percent(max(scores))}")
                detail_lines.append(f"Худший результат: {format_percent(min(scores))}")

            if last_eval_date:
                detail_lines.append(
                    f"Последний замер: {last_eval_date.strftime('%Y-%m-%d %H:%M')}"
                )

        elif object_type in ("evaluations", "evaluation"):
            evaluations_data = (
                await analytics_service.evaluation_repository.get_analytics_data(
                    organization_id=organization_id,
                    criterion_ids=None,
                    employee_ids=None,
                    date_from=None,
                    date_to=None,
                    evaluation_type_id=None,
                )
            )

            eval_data = None
            for ed in evaluations_data:
                if ed.get("id") == object_id:
                    eval_data = ed
                    break

            if not eval_data:
                return {
                    "detail_text": f"❌ Замер с ID {object_id} не найден.",
                    "object_type": object_type,
                    "object_id": object_id,
                }

            eval_date = eval_data.get("evaluation_date")
            filled_by_id = eval_data.get("filled_by_employee_id")
            evaluated_id = eval_data.get("evaluated_employee_id")
            score = eval_data.get("score_percentage", 0.0)
            total_criteria = eval_data.get("total_criteria", 0)
            passed_criteria = eval_data.get("passed_criteria", 0)
            failed_criteria = eval_data.get("failed_criteria", 0)
            comment = eval_data.get("comment")
            status = eval_data.get("status", "unknown")
            criterion_values = eval_data.get("criterion_values", [])

            # Получаем имена сотрудников
            filled_by_name = "Не указан"
            evaluated_name = "Самозаполнение"
            if filled_by_id:
                emp = await employee_service.get_by_id(filled_by_id)
                if emp:
                    filled_by_name = emp.full_name
            if evaluated_id:
                emp = await employee_service.get_by_id(evaluated_id)
                if emp:
                    evaluated_name = emp.full_name

            detail_lines.extend(
                [
                    f"📊 <b>Замер #{object_id}</b>",
                    "",
                    f"Дата: {eval_date.strftime('%Y-%m-%d %H:%M') if eval_date else 'N/A'}",
                    f"Заполнил: {filled_by_name}",
                    f"Оцениваемый: {evaluated_name}",
                    f"Балл: {format_percent(score)}",
                    f"Всего критериев: {total_criteria}",
                    f"Прошло: {passed_criteria}",
                    f"Не прошло: {failed_criteria}",
                    f"Статус: {status}",
                ]
            )

            if comment:
                detail_lines.append(f"Комментарий: {comment}")

            if criterion_values:
                detail_lines.extend(
                    [
                        "",
                        f"<b>Значения критериев ({len(criterion_values)}):</b>",
                    ]
                )
                # Получаем имена критериев
                criterion_ids = [
                    cv.get("criterion_id")
                    for cv in criterion_values
                    if cv.get("criterion_id")
                ]
                criteria_map = {}
                if criterion_ids:
                    criteria_list = await criterion_service.get_by_ids(criterion_ids)
                    for crit in criteria_list:
                        criteria_map[crit.id] = crit.name

                for cv in criterion_values[:10]:  # Показываем первые 10
                    criterion_id = cv.get("criterion_id")
                    criterion_name = criteria_map.get(
                        criterion_id, f"ID {criterion_id}"
                    )
                    value = cv.get("value")
                    value_type = cv.get("value_type", "boolean")
                    if value_type == "boolean":
                        value_str = "Да" if value else "Нет"
                    elif value_type == "number":
                        value_str = str(value)
                    elif value_type == "string":
                        value_str = f"'{value}'"
                    else:
                        value_str = str(value)
                    detail_lines.append(f"  • {criterion_name}: {value_str}")
                if len(criterion_values) > 10:
                    detail_lines.append(f"  ... и еще {len(criterion_values) - 10}")

        elif object_type in ("criteria", "criterion"):
            criterion = await criterion_service.get_by_id(object_id)
            if not criterion:
                return {
                    "detail_text": f"❌ Критерий с ID {object_id} не найден.",
                    "object_type": object_type,
                    "object_id": object_id,
                }

            detail_lines.extend(
                [
                    f"📋 <b>Критерий: {criterion.name}</b>",
                    "",
                    f"ID: {criterion.id}",
                    f"Код: {criterion.code}",
                    f"Тип значения: {criterion.value_type}",
                    f"Категория ID: {criterion.category_id or 'Нет'}",
                    f"Обязательный: {'Да' if criterion.is_required else 'Нет'}",
                    f"Активен: {'Да' if criterion.is_active else 'Нет'}",
                    f"Порядок сортировки: {criterion.sort_order}",
                ]
            )

            if criterion.description:
                detail_lines.append(f"Описание: {criterion.description}")

            # Получаем статистику использования критерия
            evaluations_data = (
                await analytics_service.evaluation_repository.get_analytics_data(
                    organization_id=organization_id,
                    criterion_ids=[object_id],
                    employee_ids=None,
                    date_from=None,
                    date_to=None,
                    evaluation_type_id=None,
                )
            )

            seen_eval_ids = set()
            usage_count = 0
            for eval_data in evaluations_data:
                eval_id = eval_data.get("id")
                if eval_id and eval_id not in seen_eval_ids:
                    seen_eval_ids.add(eval_id)
                    usage_count += 1

            detail_lines.extend(
                [
                    "",
                    "<b>Статистика использования:</b>",
                    f"Использован в замерах: {usage_count}",
                ]
            )

            # Получаем наборы критериев, в которых используется этот критерий
            all_criterion_sets = await criterion_set_service.get_by_organization_id(
                organization_id
            )
            sets_with_criterion = []
            for cs in all_criterion_sets:
                cs_full = await criterion_set_service.get_by_id(cs.id)
                if (
                    cs_full
                    and hasattr(cs_full, "criterion_ids")
                    and cs_full.criterion_ids
                    and object_id in cs_full.criterion_ids
                ):
                    sets_with_criterion.append(cs.name)

            if sets_with_criterion:
                detail_lines.append(f"Входит в наборы ({len(sets_with_criterion)}):")
                for set_name in sets_with_criterion[:10]:  # Показываем первые 10
                    detail_lines.append(f"  • {set_name}")
                if len(sets_with_criterion) > 10:
                    detail_lines.append(f"  ... и еще {len(sets_with_criterion) - 10}")
            else:
                detail_lines.append("Входит в наборы: Нет")

        elif object_type in ("criterion_sets", "criterion_set"):
            criterion_set = await criterion_set_service.get_by_id(object_id)
            if not criterion_set:
                return {
                    "detail_text": f"❌ Набор критериев с ID {object_id} не найден.",
                    "object_type": object_type,
                    "object_id": object_id,
                }

            detail_lines.extend(
                [
                    f"📦 <b>Набор критериев: {criterion_set.name}</b>",
                    "",
                    f"ID: {criterion_set.id}",
                    f"Дефолтный: {'Да' if criterion_set.is_default else 'Нет'}",
                    f"Активен: {'Да' if criterion_set.is_active else 'Нет'}",
                ]
            )

            if criterion_set.description:
                detail_lines.append(f"Описание: {criterion_set.description}")

            # Получаем критерии в наборе
            criterion_ids = (
                criterion_set.criterion_ids
                if hasattr(criterion_set, "criterion_ids")
                else []
            )
            if criterion_ids:
                criteria_in_set = await criterion_service.get_by_ids(criterion_ids)
                detail_lines.extend(
                    [
                        "",
                        f"<b>Критерии в наборе ({len(criteria_in_set)}):</b>",
                    ]
                )
                for crit in criteria_in_set:
                    detail_lines.append(
                        f"  • {crit.name} (ID: {crit.id}, Код: {crit.code}, Тип: {crit.value_type})"
                    )
            else:
                detail_lines.extend(
                    [
                        "",
                        "<b>Критерии в наборе:</b>",
                        "  Нет критериев",
                    ]
                )

            # Получаем статистику использования набора
            evaluations_data = (
                await analytics_service.evaluation_repository.get_analytics_data(
                    organization_id=organization_id,
                    criterion_ids=None,
                    employee_ids=None,
                    date_from=None,
                    date_to=None,
                    evaluation_type_id=None,
                )
            )

            seen_eval_ids = set()
            usage_count = 0
            for eval_data in evaluations_data:
                eval_id = eval_data.get("id")
                eval_criterion_set_id = eval_data.get("criterion_set_id")
                if (
                    eval_id
                    and eval_id not in seen_eval_ids
                    and eval_criterion_set_id == object_id
                ):
                    seen_eval_ids.add(eval_id)
                    usage_count += 1

            detail_lines.extend(
                [
                    "",
                    "<b>Статистика использования:</b>",
                    f"Использован в замерах: {usage_count}",
                ]
            )
        else:
            # Если тип объекта не распознан
            return {
                "detail_text": f"❌ Неизвестный тип объекта: {object_type}",
                "object_type": object_type,
                "object_id": object_id,
            }

        # Проверяем, что detail_lines не пустой
        if not detail_lines:
            return {
                "detail_text": f"❌ Не удалось загрузить данные для объекта {object_id} типа {object_type}",
                "object_type": object_type,
                "object_id": object_id,
            }

        detail_text = "\n".join(detail_lines)
        is_evaluation = object_type in ("evaluations", "evaluation")

        return {
            "detail_text": detail_text,
            "object_type": object_type,
            "object_id": object_id,
            "is_evaluation": is_evaluation,
        }

    except Exception as e:
        logger.error(f"Error loading object detail: {e}", exc_info=True)
        return {
            "detail_text": f"❌ Ошибка при загрузке данных: {str(e)}",
            "object_type": object_type,
            "object_id": object_id,
            "is_evaluation": False,
        }
