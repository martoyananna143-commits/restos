"""Handlers for analytics dialog."""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Set

from aiogram import Bot
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, StartMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button
from dependency_injector.wiring import Provide, inject

from app.internal import Container
from app.internal.usecases.ai_assistant_service import AIAssistantService
from app.internal.usecases.analytics_service import AnalyticsService
from app.internal.usecases.criterion_service import CriterionService
from app.internal.usecases.criterion_set_service import CriterionSetService
from app.internal.usecases.employee_service import EmployeeService
from app.internal.usecases.evaluation_service import EvaluationService
from app.internal.usecases.evaluation_type_service import EvaluationTypeService
from app.internal.usecases.excel_report_service import ExcelReportService
from app.internal.usecases.export_data_service import ExportDataService
from app.internal.usecases.organization_service import OrganizationService
from app.internal.usecases.pdf_report_service import PDFReportService
from app.tgbot.dialogs.analytics.states import AnalyticsDialog
from app.tgbot.dialogs.greeting.states import GreetingDialog
from app.tgbot.services import broadcaster

# Per-user asyncio locks to prevent concurrent bg.update() calls
_update_locks: dict[int, asyncio.Lock] = {}

logger = logging.getLogger(__name__)

# Global set to track active AI request tasks
_active_ai_tasks: Set[asyncio.Task] = set()


async def cancel_all_ai_tasks():
    """Cancel all active AI request tasks.
    
    This function should be called during application shutdown to ensure
    all background tasks are properly cancelled.
    """
    if not _active_ai_tasks:
        return
    
    logger.info(f"Cancelling {len(_active_ai_tasks)} active AI request tasks...")
    for task in _active_ai_tasks.copy():
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    _active_ai_tasks.clear()
    logger.info("All AI request tasks cancelled")


async def on_cancel_analytics(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle cancel analytics button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.start(
        GreetingDialog.greeting,
        mode=StartMode.RESET_STACK,
    )


async def on_select_organization(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
):
    """Handle organization selection.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected organization ID.
    """
    organization_id = int(item_id)
    dialog_manager.dialog_data["organization_id"] = organization_id
    await dialog_manager.switch_to(AnalyticsDialog.select_analytics_type)


async def on_select_analytics_type(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
):
    """Handle analytics type selection.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected analytics type ID.
    """
    analytics_type = item_id
    dialog_manager.dialog_data["analytics_type"] = analytics_type

    if analytics_type == "criteria_stats":
        await dialog_manager.switch_to(AnalyticsDialog.select_criteria)
    elif analytics_type == "average_scores":
        await dialog_manager.switch_to(AnalyticsDialog.select_group_by)
    elif analytics_type == "ai_assistant":
        # Для ассистента переходим к выбору типа данных
        await dialog_manager.switch_to(AnalyticsDialog.ai_assistant_select_data)
    elif analytics_type == "objects":
        # Для объектов переходим к выбору типа объекта
        await dialog_manager.switch_to(AnalyticsDialog.objects_select_type)
    else:
        await dialog_manager.switch_to(AnalyticsDialog.display_results)


async def on_toggle_criterion(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
):
    """Handle criterion toggle for selection.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Toggled criterion ID.
    """
    criterion_id = int(item_id)
    selected_ids = dialog_manager.dialog_data.get("selected_criterion_ids", [])

    if criterion_id in selected_ids:
        selected_ids.remove(criterion_id)
    else:
        selected_ids.append(criterion_id)

    dialog_manager.dialog_data["selected_criterion_ids"] = selected_ids


async def on_toggle_employee(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
):
    """Handle employee toggle for selection.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Toggled employee ID.
    """
    employee_id = int(item_id)
    selected_ids = dialog_manager.dialog_data.get("selected_employee_ids", [])

    if employee_id in selected_ids:
        selected_ids.remove(employee_id)
    else:
        selected_ids.append(employee_id)

    dialog_manager.dialog_data["selected_employee_ids"] = selected_ids


async def on_select_group_by(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
):
    """Handle group by selection.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected group by option ID.
    """
    group_by = item_id
    dialog_manager.dialog_data["group_by"] = group_by
    await dialog_manager.switch_to(AnalyticsDialog.select_criteria)


async def on_finish_selection(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle finish selection button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    # Переходим к выбору периода или сразу к результатам
    analytics_type = dialog_manager.dialog_data.get("analytics_type")
    if analytics_type in ["criteria_stats", "average_scores"]:
        await dialog_manager.switch_to(AnalyticsDialog.select_date_range)
    else:
        await dialog_manager.switch_to(AnalyticsDialog.display_results)


async def _set_date_range(
    dialog_manager: DialogManager,
    item_id: str,
):
    """Set date range based on item_id.

    Args:
        dialog_manager: Dialog manager.
        item_id: Selected date range preset.
    """
    now = datetime.now()

    if item_id == "today":
        date_from = now.replace(hour=0, minute=0, second=0, microsecond=0)
        date_to = now
    elif item_id == "week":
        date_from = now - timedelta(days=7)
        date_to = now
    elif item_id == "month":
        date_from = now - timedelta(days=30)
        date_to = now
    elif item_id == "quarter":
        date_from = now - timedelta(days=90)
        date_to = now
    elif item_id == "year":
        date_from = now - timedelta(days=365)
        date_to = now
    else:  # all_time
        date_from = None
        date_to = None

    # Сохраняем даты в ISO формате строк для JSON сериализации
    dialog_manager.dialog_data["date_from"] = (
        date_from.isoformat() if date_from else None
    )
    dialog_manager.dialog_data["date_to"] = date_to.isoformat() if date_to else None
    await dialog_manager.switch_to(AnalyticsDialog.display_results)


async def on_set_date_range_today(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle today button click."""
    await _set_date_range(dialog_manager, "today")


async def on_set_date_range_week(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle week button click."""
    await _set_date_range(dialog_manager, "week")


async def on_set_date_range_month(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle month button click."""
    await _set_date_range(dialog_manager, "month")


async def on_set_date_range_quarter(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle quarter button click."""
    await _set_date_range(dialog_manager, "quarter")


async def on_set_date_range_year(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle year button click."""
    await _set_date_range(dialog_manager, "year")


async def on_set_date_range_all_time(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle all time button click."""
    await _set_date_range(dialog_manager, "all_time")


async def _handle_ai_success_response(
    ai_assistant_service: AIAssistantService,
    user_id: int,
    chat_id: int,
    user_text: str,
    result: dict,
    bg,
    is_on_ai_chat_window: bool,
):
    """Handle successful AI response.

    Args:
        ai_assistant_service: AI assistant service instance.
        user_id: User ID.
        chat_id: Chat ID.
        user_text: User question text.
        result: AI service result.
        bg: Background manager for UI updates.
        is_on_ai_chat_window: Whether user is on AI chat window.
    """
    assistant_response = result["response"]
    updated_history = result["conversation_history"]

    # Save to Redis
    await ai_assistant_service.save_conversation_data(
        user_id=user_id,
        chat_id=chat_id,
        conversation_history=updated_history,
        last_response=assistant_response,
        last_user_message=user_text,
        show_last_response=False,  # Reset to show button on return
    )
    logger.info("Conversation history saved to Redis")

    # Update window if user is on AI chat window
    if is_on_ai_chat_window and bg:
        await _update_ai_window(bg, {
            "ai_conversation_history": updated_history,
            "ai_last_response": assistant_response,
            "ai_last_user_message": user_text,
            "show_last_response": True,
            "ai_processing_message": None,  # Remove processing message
        }, "AI response", user_id)
    else:
        logger.info("AI response saved, but user is not on AI chat window")


async def _handle_ai_error_response(
    ai_assistant_service: AIAssistantService,
    user_id: int,
    chat_id: int,
    user_text: str,
    error_msg: str,
    conversation_history: list,
    bg,
    is_on_ai_chat_window: bool,
):
    """Handle AI error response.

    Args:
        ai_assistant_service: AI assistant service instance.
        user_id: User ID.
        chat_id: Chat ID.
        user_text: User question text.
        error_msg: Error message.
        conversation_history: Current conversation history.
        bg: Background manager for UI updates.
        is_on_ai_chat_window: Whether user is on AI chat window.
    """
    # Save to Redis
    await ai_assistant_service.save_conversation_data(
        user_id=user_id,
        chat_id=chat_id,
        conversation_history=conversation_history,
        last_response=error_msg,
        last_user_message=user_text,
        show_last_response=False,
    )

    # Update window if user is on AI chat window
    if is_on_ai_chat_window and bg:
        await _update_ai_window(bg, {
            "ai_last_response": error_msg,
            "ai_last_user_message": user_text,
            "show_last_response": True,
            "ai_processing_message": None,  # Remove processing message
        }, "error message", user_id)


async def _update_ai_window(bg, data: dict, update_type: str, user_id: int = 0):
    """Push a UI update through ``bg.update``, serialised per-user.

    Rate-limiting is done by the *caller* (``_process_ai_request_stream``).
    This function only ensures that concurrent ``bg.update()`` calls for
    the same user are serialised (asyncio.Lock) and that Telegram flood-
    control errors are caught gracefully.
    """
    if user_id not in _update_locks:
        _update_locks[user_id] = asyncio.Lock()

    try:
        async with _update_locks[user_id]:
            await bg.update(data)
            logger.debug("Window updated: %s", update_type)
    except Exception as e:
        err = str(e).lower()
        if "flood control" in err or "too many requests" in err or "retry after" in err:
            logger.warning("Telegram flood control hit, skipping UI update")
        else:
            logger.error("Could not update window: %s", e)


async def _process_ai_request(
    ai_assistant_service: AIAssistantService,
    user_id: int,
    chat_id: int,
    user_text: str,
    conversation_history: list,
    data_context: str,
    dialog_manager: Optional[DialogManager] = None,
    is_on_ai_chat_window: bool = False,
):
    """Process AI request in background.

    Args:
        ai_assistant_service: AI assistant service instance.
        user_id: User ID.
        chat_id: Chat ID.
        user_text: User question text.
        conversation_history: Current conversation history.
        data_context: Data context for AI.
        dialog_manager: Optional dialog manager for UI updates.
        is_on_ai_chat_window: Whether user is on AI chat window (set before task launch).
    """
    bg = None

    if dialog_manager and is_on_ai_chat_window:
        try:
            bg = dialog_manager.bg()
            logger.info("User is on AI chat window, will update automatically")
        except Exception as e:
            logger.warning(f"Cannot create bg manager: {e}")
            bg = None
    else:
        logger.info("User is NOT on AI chat window, will show button on return")

    try:
        # Process AI request using service
        result = await ai_assistant_service.process_ai_request(
            user_id=user_id,
            chat_id=chat_id,
            user_text=user_text,
            conversation_history=conversation_history,
            data_context=data_context,
        )

        if result["success"]:
            await _handle_ai_success_response(
                ai_assistant_service, user_id, chat_id, user_text,
                result, bg, is_on_ai_chat_window
            )
        else:
            # Error occurred
            error_msg = result["response"]
            await _handle_ai_error_response(
                ai_assistant_service, user_id, chat_id, user_text,
                error_msg, result["conversation_history"], bg, is_on_ai_chat_window
            )

    except Exception as e:
        logger.error(f"Error processing AI message: {e}", exc_info=True)
        error_msg = f"❌ Ошибка при обработке запроса: {str(e)}"

        await _handle_ai_error_response(
            ai_assistant_service, user_id, chat_id, user_text,
            error_msg, conversation_history, bg, is_on_ai_chat_window
        )


async def _process_ai_request_stream(
    ai_assistant_service: AIAssistantService,
    user_id: int,
    chat_id: int,
    user_text: str,
    conversation_history: list,
    data_context: str,
    dialog_manager: Optional[DialogManager] = None,
    is_on_ai_chat_window: bool = False,
):
    """Try streaming first; fall back to non-streaming after 30 s.

    Flow:
      1. Launch ``process_ai_request_stream`` (parallel streams).
      2. If it yields a valid ``completed`` result — great, use it.
      3. If it yields an ``error`` (all streams failed / timeout) —
         **don't give up** — fall back to ``process_ai_request``
         (non-streaming parallel workers) with the same context.
      4. If the non-streaming fallback also fails — then report error.
    """
    bg = None
    if dialog_manager and is_on_ai_chat_window:
        try:
            bg = dialog_manager.bg()
            logger.info("User is on AI chat window, will update with stream")
        except Exception as e:
            logger.warning(f"Cannot create bg manager: {e}")
            bg = None
    else:
        logger.info("User is NOT on AI chat window, will show button on return")

    # ------------------------------------------------------------------
    # Phase 1: streaming
    # ------------------------------------------------------------------
    stream_succeeded = False
    stream_error_msg: Optional[str] = None
    last_update_text = ""
    last_update_time = 0.0
    _SENTENCE_ENDINGS = {". ", "! ", "? ", ".\n", "!\n", "?\n"}

    try:
        async for stream_data in ai_assistant_service.process_ai_request_stream(
            user_id=user_id,
            chat_id=chat_id,
            user_text=user_text,
            conversation_history=conversation_history,
            data_context=data_context,
        ):
            # --- error from stream ---
            if stream_data.get("error"):
                stream_error_msg = stream_data["error"]
                logger.warning("Stream phase failed: %s — will try non-stream fallback", stream_error_msg)
                break  # don't return — fall through to Phase 2

            # --- completed ---
            if stream_data.get("completed"):
                full_text = stream_data.get("full_text", "")
                updated_history = stream_data.get(
                    "conversation_history", conversation_history
                )

                if bg and is_on_ai_chat_window and full_text:
                    await _update_ai_window(bg, {
                        "ai_conversation_history": updated_history,
                        "ai_last_response": full_text,
                        "ai_last_user_message": user_text,
                        "show_last_response": True,
                        "ai_processing_message": None,
                    }, "AI stream completed", user_id)

                await ai_assistant_service.save_conversation_data(
                    user_id=user_id,
                    chat_id=chat_id,
                    conversation_history=updated_history,
                    last_response=full_text,
                    last_user_message=user_text,
                    show_last_response=False,
                )
                logger.info("Stream conversation history saved to Redis")
                stream_succeeded = True
                return  # done!

            # --- intermediate chunk ---
            chunk = stream_data.get("chunk")
            if chunk and bg and is_on_ai_chat_window:
                full_text = stream_data.get("full_text", "")
                text_delta = len(full_text) - len(last_update_text)
                now = time.time()
                time_delta = now - last_update_time

                should_update = False
                if time_delta >= 1.0 and text_delta >= 100:
                    should_update = True
                elif time_delta >= 1.0:
                    for ending in _SENTENCE_ENDINGS:
                        if ending in chunk or full_text.endswith(ending.rstrip()):
                            should_update = True
                            break

                if should_update:
                    await _update_ai_window(bg, {
                        "ai_conversation_history": stream_data.get(
                            "conversation_history", conversation_history
                        ),
                        "ai_last_response": full_text,
                        "ai_last_user_message": user_text,
                        "show_last_response": True,
                        "ai_processing_message": None,
                    }, "AI stream chunk", user_id)
                    last_update_text = full_text
                    last_update_time = now

    except Exception as e:
        logger.error(f"Stream phase exception: {e}", exc_info=True)
        stream_error_msg = str(e)

    if stream_succeeded:
        return

    # ------------------------------------------------------------------
    # Phase 2: non-streaming fallback
    # ------------------------------------------------------------------
    logger.info(
        "[fallback] Streaming failed (%s) — switching to non-stream request",
        stream_error_msg or "unknown",
    )

    # Update UI to let the user know we're still trying
    if bg and is_on_ai_chat_window:
        try:
            await _update_ai_window(bg, {
                "ai_processing_message": (
                    "🤖 Стриминг не удался, пробую другой способ...\n\n"
                    "💡 Ожидайте, это может занять до 20 секунд."
                ),
            }, "fallback notice", user_id)
        except Exception:
            pass

    try:
        result = await ai_assistant_service.process_ai_request(
            user_id=user_id,
            chat_id=chat_id,
            user_text=user_text,
            conversation_history=conversation_history,
            data_context=data_context,
        )

        if result["success"]:
            logger.info("[fallback] Non-stream request succeeded")
            await _handle_ai_success_response(
                ai_assistant_service, user_id, chat_id, user_text,
                result, bg, is_on_ai_chat_window,
            )
        else:
            logger.warning("[fallback] Non-stream request also failed")
            await _handle_ai_error_response(
                ai_assistant_service, user_id, chat_id, user_text,
                result["response"],
                result["conversation_history"],
                bg, is_on_ai_chat_window,
            )

    except Exception as e:
        logger.error(f"[fallback] Non-stream exception: {e}", exc_info=True)
        await _handle_ai_error_response(
            ai_assistant_service, user_id, chat_id, user_text,
            f"❌ Ошибка при обработке запроса: {e}",
            conversation_history, bg, is_on_ai_chat_window,
        )


@inject
async def on_ai_message(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    ai_assistant_service: AIAssistantService = Provide[Container.ai_assistant_service],
    analytics_service: AnalyticsService = Provide[Container.analytics_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
    criterion_service: CriterionService = Provide[Container.criterion_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
):
    """Handle user message in AI assistant chat.

    Args:
        message: User message.
        widget: MessageInput widget.
        dialog_manager: Dialog manager.
        ai_assistant_service: AI assistant service instance (injected).
        analytics_service: Analytics service (injected, for fallback data loading).
        organization_service: Organization service (injected, for fallback data loading).
        criterion_service: Criterion service (injected, for fallback data loading).
        employee_service: Employee service (injected, for fallback data loading).
    """

    user_text = message.text or ""
    if not user_text.strip():
        await dialog_manager.show()
        return

    chat_id = message.chat.id

    user_id = None
    if message.from_user:
        user_id = message.from_user.id
    elif dialog_manager.middleware_data.get("user_data"):
        user_id = dialog_manager.middleware_data["user_data"].get("telegram_id")

    if not user_id:
        await dialog_manager.show()
        return

    ai_service = ai_assistant_service

    # Load conversation history from Redis if not in dialog_data
    conversation_history = dialog_manager.dialog_data.get("ai_conversation_history", [])
    if not conversation_history:
        stored_data = await ai_service.load_conversation_data(user_id, chat_id)
        conversation_history = stored_data.get("ai_conversation_history", [])

    # ──────────────────────────────────────────────────────────────
    # Get data_context with FALLBACK loading.
    # The getter (get_ai_assistant_data) normally caches this, but
    # in some edge cases the cache may be empty (race conditions,
    # getter errors, dialog_data eviction).  If so, we reload here.
    # ──────────────────────────────────────────────────────────────
    data_context = dialog_manager.dialog_data.get("ai_data_context", "")
    data_type = dialog_manager.dialog_data.get("ai_data_type", "none")
    organization_id = dialog_manager.dialog_data.get("organization_id")

    if not data_context and data_type != "none" and organization_id:
        logger.warning(
            "data_context is EMPTY but data_type=%s, org_id=%s — fallback loading!",
            data_type, organization_id,
        )
        try:
            from app.tgbot.dialogs.analytics.getters import _load_data_context

            org = await organization_service.get_by_id(organization_id)
            org_name = org.name if org else f"Организация #{organization_id}"
            data_context = await _load_data_context(
                data_type=data_type,
                organization_id=organization_id,
                org_name=org_name,
                dialog_manager=dialog_manager,
                analytics_service=analytics_service,
                organization_service=organization_service,
                criterion_service=criterion_service,
                employee_service=employee_service,
            )
            # Cache it so subsequent messages don't need to reload
            dialog_manager.dialog_data["ai_data_context"] = data_context
            logger.info(
                "Fallback loaded data_context: %d chars", len(data_context)
            )
        except Exception as e:
            logger.error("Fallback data_context loading failed: %s", e, exc_info=True)
            data_context = ""

    if data_context:
        logger.info(
            "AI request with data_context: %d chars, data_type=%s",
            len(data_context), data_type,
        )
    else:
        logger.info("AI request WITHOUT data_context (data_type=%s)", data_type)

    # Set processing message - MessageInput will automatically update the window
    dialog_manager.dialog_data["ai_processing_message"] = (
        "🤖 Ассистент обрабатывает ваш запрос...\n\n"
        "💡 Вы можете перейти в другие окна и вернуться позже."
    )

    # Check if user is on AI chat window (before launching background task)
    from app.tgbot.dialogs.analytics.states import AnalyticsDialog

    is_on_ai_chat: bool = False
    try:
        current_context = dialog_manager.current_context()
        is_on_ai_chat = bool(
            current_context
            and current_context.state == AnalyticsDialog.ai_assistant_chat
        )
    except Exception as e:
        logger.warning(f"Cannot check current state: {e}")

    # Create and track the background task with streaming
    task = asyncio.create_task(
        _process_ai_request_stream(
            ai_service,
            user_id,
            chat_id,
            user_text,
            conversation_history,
            data_context,
            dialog_manager,
            is_on_ai_chat,
        )
    )
    _active_ai_tasks.add(task)
    task.add_done_callback(_active_ai_tasks.discard)


@inject
async def on_select_ai_data_type(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
    ai_assistant_service: AIAssistantService = Provide[Container.ai_assistant_service],
):
    """Handle AI data type selection.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected data type ID.
        ai_assistant_service: AI assistant service instance (injected).
    """
    data_type = item_id
    dialog_manager.dialog_data["ai_data_type"] = data_type
    # Очищаем историю при выборе нового типа данных
    dialog_manager.dialog_data["ai_conversation_history"] = []
    dialog_manager.dialog_data["ai_last_response"] = None
    dialog_manager.dialog_data["ai_data_context"] = ""
    # Сбрасываем пагинацию
    dialog_manager.dialog_data["ai_data_page"] = 0
    
    # Очищаем данные в Redis чтобы при загрузке использовался новый data_context
    user_id = None
    if callback.from_user:
        user_id = callback.from_user.id
    if user_id and callback.message:
        chat_id = callback.message.chat.id
        await ai_assistant_service.delete_conversation_data(user_id, chat_id)
        logger.info(f"Cleared AI conversation data for user {user_id} on data type change")
    
    await dialog_manager.switch_to(AnalyticsDialog.ai_assistant_view_data)


@inject
async def on_start_ai_chat_without_data(
    callback: CallbackQuery, 
    button: Button, 
    dialog_manager: DialogManager,
    ai_assistant_service: AIAssistantService = Provide[Container.ai_assistant_service],
):
    """Start AI chat without loading data.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        ai_assistant_service: AI assistant service instance (injected).
    """
    # Устанавливаем тип данных как "none" для работы без данных
    dialog_manager.dialog_data["ai_data_type"] = "none"
    # Очищаем историю
    dialog_manager.dialog_data["ai_conversation_history"] = []
    dialog_manager.dialog_data["ai_last_response"] = None
    dialog_manager.dialog_data["ai_data_context"] = ""
    
    # Очищаем данные в Redis
    user_id = None
    if callback.from_user:
        user_id = callback.from_user.id
    if user_id and callback.message:
        chat_id = callback.message.chat.id
        await ai_assistant_service.delete_conversation_data(user_id, chat_id)
        logger.info(f"Cleared AI conversation data for user {user_id} on chat without data")
    
    await dialog_manager.switch_to(AnalyticsDialog.ai_assistant_chat)


async def on_ai_data_next_page(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate to next page of AI data.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    current_page = dialog_manager.dialog_data.get("ai_data_page", 0)
    dialog_manager.dialog_data["ai_data_page"] = current_page + 1

    # Используем dialog_manager.show() для бесшовного обновления окна (текст + клавиатура)
    await dialog_manager.show()


async def on_ai_data_prev_page(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate to previous page of AI data.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    current_page = dialog_manager.dialog_data.get("ai_data_page", 0)
    if current_page > 0:
        dialog_manager.dialog_data["ai_data_page"] = current_page - 1

    # Используем dialog_manager.show() для бесшовного обновления окна (текст + клавиатура)
    await dialog_manager.show()


async def on_ai_data_start_chat(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Start AI chat after viewing data.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.switch_to(AnalyticsDialog.ai_assistant_chat)


@inject
async def on_clear_ai_history(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    ai_assistant_service: AIAssistantService = Provide[Container.ai_assistant_service],
):
    """Clear AI conversation history.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        ai_assistant_service: AI assistant service instance (injected).
    """

    # Get user_id and chat_id
    user_id = None
    chat_id = None

    if callback.from_user:
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id if callback.message else None
    elif dialog_manager.middleware_data.get("user_data"):
        user_id = dialog_manager.middleware_data["user_data"].get("telegram_id")

    # Clear dialog_data
    dialog_manager.dialog_data["ai_conversation_history"] = []
    dialog_manager.dialog_data.pop("ai_last_response", None)
    dialog_manager.dialog_data.pop("ai_last_user_message", None)
    dialog_manager.dialog_data.pop("show_last_response", None)
    dialog_manager.dialog_data.pop("ai_processing_message", None)

    # Clear Redis
    if user_id and chat_id:
        await ai_assistant_service.delete_conversation_data(user_id, chat_id)

    await dialog_manager.show()


async def on_show_last_ai_response(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Show last AI response.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    last_response = dialog_manager.dialog_data.get("ai_last_response")

    if last_response:
        # Помечаем, что нужно показать ответ
        dialog_manager.dialog_data["show_last_response"] = True
        # Обновляем окно чата, чтобы показать последний ответ
        await dialog_manager.show()
    else:
        await callback.answer("Нет сохраненных ответов")


# ========== Objects section handlers ==========


async def on_select_object_type(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
):
    """Handle object type selection.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected object type ID.
    """
    dialog_manager.dialog_data["object_type"] = item_id
    dialog_manager.dialog_data["objects_page"] = 0
    await dialog_manager.switch_to(AnalyticsDialog.objects_list)


async def on_objects_next_page(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate to next page of objects.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    current_page = dialog_manager.dialog_data.get("objects_page", 0)
    dialog_manager.dialog_data["objects_page"] = current_page + 1

    # Используем dialog_manager.show() для бесшовного обновления окна
    await dialog_manager.show()


async def on_objects_prev_page(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate to previous page of objects.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    current_page = dialog_manager.dialog_data.get("objects_page", 0)
    if current_page > 0:
        dialog_manager.dialog_data["objects_page"] = current_page - 1

    # Используем dialog_manager.show() для бесшовного обновления окна
    await dialog_manager.show()


async def on_select_object(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
):
    """Handle object selection for detail view.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected object ID.
    """

    # НЕ перезаписываем object_type, так как он уже установлен правильно при выборе типа объекта
    # object_type должен оставаться в множественном числе ("employees", "evaluations", "criteria", "criterion_sets")
    # для корректной работы get_objects_list_data

    dialog_manager.dialog_data["selected_object_id"] = int(item_id)
    await dialog_manager.switch_to(AnalyticsDialog.object_detail)


async def _validate_export_params(
    dialog_manager: DialogManager,
    callback: CallbackQuery,
) -> tuple[bool, Optional[str], Optional[int], Optional[str]]:
    """Validate parameters for object export.

    Args:
        dialog_manager: Dialog manager.
        callback: Callback query.

    Returns:
        Tuple of (is_valid, organization_name, object_id, object_type).
    """
    object_type = dialog_manager.dialog_data.get("object_type")
    object_id = dialog_manager.dialog_data.get("selected_object_id")

    if not object_id:
        await callback.answer("❌ Объект не выбран", show_alert=True)
        return False, None, None, None

    organization_id = dialog_manager.dialog_data.get("organization_id")
    if not organization_id:
        await callback.answer("❌ Организация не выбрана", show_alert=True)
        return False, None, None, None

    return True, organization_id, object_id, object_type


async def _send_export_file(
    bot: Bot,
    callback: CallbackQuery,
    file_path: str,
    object_type: str,
    object_id: int,
    file_type: str,
):
    """Send exported file to user.

    Args:
        bot: Bot instance.
        callback: Callback query.
        file_path: Path to the exported file.
        object_type: Type of exported object.
        object_id: ID of exported object.
        file_type: Type of file (PDF/Excel).
    """
    if file_path:
        await broadcaster.send_document(
            bot,
            callback.from_user.id,
            Path(file_path),
            caption=f"📄 {file_type} отчет по {object_type} #{object_id}",
        )
        await callback.answer(f"✅ {file_type} отчет успешно сгенерирован")
    else:
        await callback.answer(f"❌ Не удалось сгенерировать {file_type}")


async def _export_employee_pdf(
    organization_name: str,
    object_id: int,
    pdf_report_service,
    employee_service,
    analytics_service,
) -> Optional[str]:
    """Export employee to PDF.

    Args:
        organization_name: Name of organization.
        object_id: Employee ID.
        pdf_report_service: PDF report service.
        employee_service: Employee service.
        analytics_service: Analytics service.

    Returns:
        Path to generated PDF file or None.
    """
    employee = await employee_service.get_by_id(object_id)
    if not employee:
        return None

    # Получаем статистику по замерам
    evaluations_data = (
        await analytics_service.evaluation_repository.get_analytics_data(
            organization_id=None,  # We'll filter by employee
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

    avg_score = sum(scores) / len(scores) if scores else None
    best_score = max(scores) if scores else None
    worst_score = min(scores) if scores else None

    return pdf_report_service.generate_employee_report(
        employee_id=employee.id,
        employee_name=employee.full_name,
        organization_name=organization_name,
        position=employee.position,
        phone=employee.phone,
        telegram_id=employee.telegram_id,
        username=employee.username,
        hire_date=employee.hire_date.strftime("%Y-%m-%d")
        if employee.hire_date
        else None,
        is_active=employee.is_active,
        total_evaluations=eval_count,
        avg_score=avg_score,
        best_score=best_score,
        worst_score=worst_score,
        last_evaluation_date=last_eval_date.strftime("%Y-%m-%d %H:%M")
        if last_eval_date
        else None,
    )


async def _export_evaluation_pdf(
    organization_name: str,
    object_id: int,
    pdf_report_service,
    analytics_service,
    evaluation_service,
    evaluation_type_service,
    employee_service,
    criterion_service,
    criterion_set_service,
    export_data_service,
) -> Optional[str]:
    """Export evaluation to PDF.

    Args:
        organization_name: Name of organization.
        object_id: Evaluation ID.
        pdf_report_service: PDF report service.
        analytics_service: Analytics service.
        evaluation_service: Evaluation service.
        evaluation_type_service: Evaluation type service.
        employee_service: Employee service.
        criterion_service: Criterion service.
        criterion_set_service: Criterion set service.
        export_data_service: Export data service.

    Returns:
        Path to generated PDF file or None.
    """
    # Получаем данные замера
    evaluation = await evaluation_service.get_by_id(object_id)
    if not evaluation:
        return None

    # Получаем тип оценки
    evaluation_type = await evaluation_type_service.get_by_id(
        evaluation.evaluation_type_id
    )
    evaluation_type_name = (
        evaluation_type.name if evaluation_type else "Не указано"
    )

    # Получаем имена сотрудников
    filled_by_id = evaluation.filled_by_employee_id
    evaluated_id = evaluation.evaluated_employee_id
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

    # Получаем набор критериев
    criterion_set_name = None
    if evaluation.criterion_set_id:
        criterion_set = await criterion_set_service.get_by_id(
            evaluation.criterion_set_id
        )
        if criterion_set:
            criterion_set_name = criterion_set.name

    # Prepare evaluation data using service
    eval_data = await export_data_service.prepare_evaluation_data_for_export(
        evaluation_id=object_id,
        criterion_service=criterion_service,
        criterion_set_service=criterion_set_service,
        employee_service=employee_service,
        evaluation_type_service=evaluation_type_service,
    )

    criteria_list = eval_data["criteria"]
    total_criteria = eval_data["total_criteria"]
    passed_criteria = eval_data["passed_criteria"]
    failed_criteria = eval_data["failed_criteria"]
    score_percentage = eval_data["score_percentage"]
    boolean_criteria_count = eval_data["boolean_criteria_count"]

    evaluation_date = (
        evaluation.evaluation_date.strftime("%d.%m.%Y %H:%M")
        if evaluation.evaluation_date
        else datetime.now().strftime("%d.%m.%Y %H:%M")
    )

    return pdf_report_service.generate_evaluation_report(
        evaluation_id=evaluation.id,
        evaluation_type_name=evaluation_type_name,
        organization_name=organization_name,
        evaluated_employee_name=evaluated_name,
        filled_by_employee_name=filled_by_name,
        evaluation_date=evaluation_date,
        criteria=criteria_list,
        total_criteria=total_criteria,
        passed_criteria=passed_criteria,
        failed_criteria=failed_criteria,
        score_percentage=score_percentage,
        criterion_set_name=criterion_set_name,
        boolean_criteria_count=boolean_criteria_count
        if boolean_criteria_count > 0
        else None,
    )


async def _export_criterion_pdf(
    organization_name: str,
    object_id: int,
    pdf_report_service,
    criterion_service,
    analytics_service,
    criterion_set_service,
    export_data_service,
) -> Optional[str]:
    """Export criterion to PDF.

    Args:
        organization_name: Name of organization.
        object_id: Criterion ID.
        pdf_report_service: PDF report service.
        criterion_service: Criterion service.
        analytics_service: Analytics service.
        criterion_set_service: Criterion set service.
        export_data_service: Export data service.

    Returns:
        Path to generated PDF file or None.
    """
    criterion = await criterion_service.get_by_id(object_id)
    if not criterion:
        return None

    # Prepare criterion statistics using service
    criterion_stats = await export_data_service.prepare_criterion_statistics(
        criterion_id=object_id,
        organization_id=None,  # Not needed for basic info
        analytics_service=analytics_service,
        criterion_set_service=criterion_set_service,
    )

    usage_count = criterion_stats["usage_count"]
    sets_with_criterion = criterion_stats["criterion_sets"]

    return pdf_report_service.generate_criterion_report(
        criterion_id=criterion.id,
        criterion_name=criterion.name,
        organization_name=organization_name,
        code=criterion.code,
        value_type=criterion.value_type,
        category_id=criterion.category_id,
        is_required=criterion.is_required,
        is_active=criterion.is_active,
        description=criterion.description,
        sort_order=criterion.sort_order,
        usage_count=usage_count,
        criterion_sets=sets_with_criterion,
    )


async def _export_criterion_set_pdf(
    organization_name: str,
    object_id: int,
    pdf_report_service,
    criterion_set_service,
    criterion_service,
    analytics_service,
) -> Optional[str]:
    """Export criterion set to PDF.

    Args:
        organization_name: Name of organization.
        object_id: Criterion set ID.
        pdf_report_service: PDF report service.
        criterion_set_service: Criterion set service.
        criterion_service: Criterion service.
        analytics_service: Analytics service.

    Returns:
        Path to generated PDF file or None.
    """
    criterion_set = await criterion_set_service.get_by_id(object_id)
    if not criterion_set:
        return None

    criterion_ids = (
        criterion_set.criterion_ids
        if hasattr(criterion_set, "criterion_ids")
        and criterion_set.criterion_ids
        else []
    )
    criteria_list = []
    if criterion_ids:
        criteria = await criterion_service.get_by_ids(criterion_ids)
        criteria_list = [
            {
                "name": crit.name,
                "code": crit.code,
                "value_type": crit.value_type,
            }
            for crit in criteria
        ]

    # Get usage count
    usage_count = 0
    evaluations_data = await analytics_service.evaluation_repository.get_analytics_data(
        organization_id=None,
    )

    seen_eval_ids = set()
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

    return pdf_report_service.generate_criterion_set_report(
        criterion_set_id=criterion_set.id,
        criterion_set_name=criterion_set.name,
        organization_name=organization_name,
        is_default=criterion_set.is_default,
        is_active=criterion_set.is_active,
        description=criterion_set.description,
        criteria=criteria_list,
        usage_count=usage_count,
    )


async def _generate_pdf_report(
    organization_name: str,
    object_id: int,
    object_type: str,
    pdf_report_service,
    analytics_service,
    evaluation_service,
    evaluation_type_service,
    employee_service,
    criterion_service,
    criterion_set_service,
    export_data_service,
) -> Optional[str]:
    """Generate PDF report for object.

    Args:
        organization_name: Name of organization.
        object_id: Object ID.
        object_type: Type of object.
        pdf_report_service: PDF report service.
        analytics_service: Analytics service.
        evaluation_service: Evaluation service.
        evaluation_type_service: Evaluation type service.
        employee_service: Employee service.
        criterion_service: Criterion service.
        criterion_set_service: Criterion set service.
        export_data_service: Export data service.

    Returns:
        Path to generated PDF file or None.
    """
    # Normalize object type
    if object_type in ("employees", "employee"):
        return await _export_employee_pdf(
            organization_name, object_id, pdf_report_service,
            employee_service, analytics_service
        )
    elif object_type in ("evaluations", "evaluation"):
        return await _export_evaluation_pdf(
            organization_name, object_id, pdf_report_service,
            analytics_service, evaluation_service, evaluation_type_service,
            employee_service, criterion_service, criterion_set_service,
            export_data_service
        )
    elif object_type in ("criteria", "criterion"):
        return await _export_criterion_pdf(
            organization_name, object_id, pdf_report_service,
            criterion_service, analytics_service, criterion_set_service,
            export_data_service
        )
    elif object_type in ("criterion_sets", "criterion_set"):
        return await _export_criterion_set_pdf(
            organization_name, object_id, pdf_report_service,
            criterion_set_service, criterion_service, analytics_service
        )
    else:
        return None


@inject
async def on_export_object_pdf(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    pdf_report_service: PDFReportService = Provide[Container.pdf_report_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
    analytics_service: AnalyticsService = Provide[Container.analytics_service],
    criterion_service: CriterionService = Provide[Container.criterion_service],
    criterion_set_service: CriterionSetService = Provide[
        Container.criterion_set_service
    ],
    evaluation_service: EvaluationService = Provide[Container.evaluation_service],
    evaluation_type_service: EvaluationTypeService = Provide[
        Container.evaluation_type_service
    ],
    export_data_service: ExportDataService = Provide[Container.export_data_service],
):
    """Export object to PDF.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        pdf_report_service: PDF report service instance (injected).
        employee_service: Employee service instance (injected).
        organization_service: Organization service instance (injected).
        analytics_service: Analytics service instance (injected).
        criterion_service: Criterion service instance (injected).
        criterion_set_service: Criterion set service instance (injected).
    """
    await callback.answer("Генерация PDF...")

    # Validate parameters
    is_valid, organization_id, object_id, object_type = await _validate_export_params(
        dialog_manager, callback
    )
    if not is_valid:
        return

    try:
        # Получаем данные организации
        if not isinstance(organization_id, int):
            await callback.answer("❌ Ошибка: некорректный ID организации")
            return

        organization = await organization_service.get_by_id(organization_id)
        if not organization:
            await callback.answer("❌ Организация не найдена")
            return

        # Get bot instance
        bot = dialog_manager.middleware_data.get("bot")
        if not bot and dialog_manager.event:
            bot = getattr(dialog_manager.event, "bot", None)

        if not bot or not isinstance(bot, Bot) or not callback.from_user:
            await callback.answer("❌ Ошибка получения бота", show_alert=True)
            return

        # Validate required parameters
        if not isinstance(object_id, int) or not isinstance(object_type, str):
            await callback.answer("❌ Ошибка: некорректные параметры объекта", show_alert=True)
            return

        # Generate PDF report
        pdf_path = await _generate_pdf_report(
            organization.name, object_id, object_type,
            pdf_report_service, analytics_service, evaluation_service,
            evaluation_type_service, employee_service, criterion_service,
            criterion_set_service, export_data_service
        )

        if not pdf_path:
            await callback.answer("❌ Не удалось сгенерировать PDF", show_alert=True)
            return

        # Send file to user
        await _send_export_file(bot, callback, pdf_path, object_type, object_id, "PDF")

    except Exception as e:
        logger.error(f"Error exporting object to PDF: {e}", exc_info=True)
        await callback.answer(f"❌ Ошибка при экспорте: {str(e)}", show_alert=True)


async def _export_employee_excel(
    organization_name: str,
    object_id: int,
    excel_report_service,
    employee_service,
    analytics_service,
    export_data_service,
) -> Optional[str]:
    """Export employee to Excel.

    Args:
        organization_name: Name of organization.
        object_id: Employee ID.
        excel_report_service: Excel report service.
        employee_service: Employee service.
        analytics_service: Analytics service.
        export_data_service: Export data service.

    Returns:
        Path to generated Excel file or None.
    """
    employee = await employee_service.get_by_id(object_id)
    if not employee:
        return None

    # Prepare employee statistics using service
    employee_stats = await export_data_service.prepare_employee_statistics(
        employee_id=object_id,
        organization_id=None,  # Not needed for basic info
        analytics_service=analytics_service,
    )

    eval_count = employee_stats["total_evaluations"]
    avg_score = employee_stats["avg_score"]
    best_score = employee_stats["best_score"]
    worst_score = employee_stats["worst_score"]
    last_eval_date_str = employee_stats["last_evaluation_date"]

    return excel_report_service.generate_employee_report(
        employee_id=employee.id,
        employee_name=employee.full_name,
        organization_name=organization_name,
        position=employee.position,
        phone=employee.phone,
        telegram_id=employee.telegram_id,
        username=employee.username,
        hire_date=employee.hire_date.strftime("%Y-%m-%d")
        if employee.hire_date
        else None,
        is_active=employee.is_active,
        total_evaluations=eval_count,
        avg_score=avg_score,
        best_score=best_score,
        worst_score=worst_score,
        last_evaluation_date=last_eval_date_str,
    )


async def _export_evaluation_excel(
    organization_name: str,
    object_id: int,
    excel_report_service,
    analytics_service,
    evaluation_service,
    evaluation_type_service,
    employee_service,
    criterion_service,
    criterion_set_service,
    export_data_service,
) -> Optional[str]:
    """Export evaluation to Excel.

    Args:
        organization_name: Name of organization.
        object_id: Evaluation ID.
        excel_report_service: Excel report service.
        analytics_service: Analytics service.
        evaluation_service: Evaluation service.
        evaluation_type_service: Evaluation type service.
        employee_service: Employee service.
        criterion_service: Criterion service.
        criterion_set_service: Criterion set service.
        export_data_service: Export data service.

    Returns:
        Path to generated Excel file or None.
    """
    # Получаем данные замера
    evaluation = await evaluation_service.get_by_id(object_id)
    if not evaluation:
        return None

    # Получаем тип оценки
    evaluation_type = await evaluation_type_service.get_by_id(
        evaluation.evaluation_type_id
    )
    evaluation_type_name = (
        evaluation_type.name if evaluation_type else "Не указано"
    )

    # Получаем имена сотрудников
    filled_by_id = evaluation.filled_by_employee_id
    evaluated_id = evaluation.evaluated_employee_id
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

    # Получаем набор критериев
    criterion_set_name = None
    if evaluation.criterion_set_id:
        criterion_set = await criterion_set_service.get_by_id(
            evaluation.criterion_set_id
        )
        if criterion_set:
            criterion_set_name = criterion_set.name

    # Prepare evaluation data using service
    eval_data = await export_data_service.prepare_evaluation_data_for_export(
        evaluation_id=object_id,
        criterion_service=criterion_service,
        criterion_set_service=criterion_set_service,
        employee_service=employee_service,
        evaluation_type_service=evaluation_type_service,
    )

    criteria_list = eval_data["criteria"]
    total_criteria = eval_data["total_criteria"]
    passed_criteria = eval_data["passed_criteria"]
    failed_criteria = eval_data["failed_criteria"]
    score_percentage = eval_data["score_percentage"]
    boolean_criteria_count = eval_data["boolean_criteria_count"]

    evaluation_date = (
        evaluation.evaluation_date.strftime("%d.%m.%Y %H:%M")
        if evaluation.evaluation_date
        else datetime.now().strftime("%d.%m.%Y %H:%M")
    )

    return excel_report_service.generate_evaluation_report(
        evaluation_id=evaluation.id,
        evaluation_type_name=evaluation_type_name,
        organization_name=organization_name,
        evaluated_employee_name=evaluated_name,
        filled_by_employee_name=filled_by_name,
        evaluation_date=evaluation_date,
        criteria=criteria_list,
        total_criteria=total_criteria,
        passed_criteria=passed_criteria,
        failed_criteria=failed_criteria,
        score_percentage=score_percentage,
        criterion_set_name=criterion_set_name,
        boolean_criteria_count=boolean_criteria_count
        if boolean_criteria_count > 0
        else None,
    )


async def _export_criterion_excel(
    organization_name: str,
    object_id: int,
    excel_report_service,
    criterion_service,
    analytics_service,
    criterion_set_service,
    export_data_service,
) -> Optional[str]:
    """Export criterion to Excel.

    Args:
        organization_name: Name of organization.
        object_id: Criterion ID.
        excel_report_service: Excel report service.
        criterion_service: Criterion service.
        analytics_service: Analytics service.
        criterion_set_service: Criterion set service.
        export_data_service: Export data service.

    Returns:
        Path to generated Excel file or None.
    """
    criterion = await criterion_service.get_by_id(object_id)
    if not criterion:
        return None

    # Prepare criterion statistics using service
    criterion_stats = await export_data_service.prepare_criterion_statistics(
        criterion_id=object_id,
        organization_id=None,  # Not needed for basic info
        analytics_service=analytics_service,
        criterion_set_service=criterion_set_service,
    )

    usage_count = criterion_stats["usage_count"]
    sets_with_criterion = criterion_stats["criterion_sets"]

    return excel_report_service.generate_criterion_report(
        criterion_id=criterion.id,
        criterion_name=criterion.name,
        organization_name=organization_name,
        code=criterion.code,
        value_type=criterion.value_type,
        category_id=criterion.category_id,
        is_required=criterion.is_required,
        is_active=criterion.is_active,
        description=criterion.description,
        sort_order=criterion.sort_order,
        usage_count=usage_count,
        criterion_sets=sets_with_criterion,
    )


async def _export_criterion_set_excel(
    organization_name: str,
    object_id: int,
    excel_report_service,
    criterion_set_service,
    criterion_service,
    analytics_service,
    export_data_service,
) -> Optional[str]:
    """Export criterion set to Excel.

    Args:
        organization_name: Name of organization.
        object_id: Criterion set ID.
        excel_report_service: Excel report service.
        criterion_set_service: Criterion set service.
        criterion_service: Criterion service.
        analytics_service: Analytics service.
        export_data_service: Export data service.

    Returns:
        Path to generated Excel file or None.
    """
    criterion_set = await criterion_set_service.get_by_id(object_id)
    if not criterion_set:
        return None

    # Получаем критерии в наборе
    criterion_ids = (
        criterion_set.criterion_ids
        if hasattr(criterion_set, "criterion_ids")
        and criterion_set.criterion_ids
        else []
    )
    criteria_list = []
    if criterion_ids:
        criteria = await criterion_service.get_by_ids(criterion_ids)
        criteria_list = [
            {
                "name": crit.name,
                "code": crit.code,
                "value_type": crit.value_type,
            }
            for crit in criteria
        ]

    # Prepare criterion set statistics using service
    criterion_set_stats = (
        await export_data_service.prepare_criterion_set_statistics(
            criterion_set_id=object_id,
            organization_id=None,  # Not needed for basic info
            analytics_service=analytics_service,
        )
    )

    usage_count = criterion_set_stats["usage_count"]

    return excel_report_service.generate_criterion_set_report(
        criterion_set_id=criterion_set.id,
        criterion_set_name=criterion_set.name,
        organization_name=organization_name,
        is_default=criterion_set.is_default,
        is_active=criterion_set.is_active,
        description=criterion_set.description,
        criteria=criteria_list,
        usage_count=usage_count,
    )


async def _generate_excel_report(
    organization_name: str,
    object_id: int,
    object_type: str,
    excel_report_service,
    analytics_service,
    evaluation_service,
    evaluation_type_service,
    employee_service,
    criterion_service,
    criterion_set_service,
    export_data_service,
) -> Optional[str]:
    """Generate Excel report for object.

    Args:
        organization_name: Name of organization.
        object_id: Object ID.
        object_type: Type of object.
        excel_report_service: Excel report service.
        analytics_service: Analytics service.
        evaluation_service: Evaluation service.
        evaluation_type_service: Evaluation type service.
        employee_service: Employee service.
        criterion_service: Criterion service.
        criterion_set_service: Criterion set service.
        export_data_service: Export data service.

    Returns:
        Path to generated Excel file or None.
    """
    # Normalize object type
    if object_type in ("employees", "employee"):
        return await _export_employee_excel(
            organization_name, object_id, excel_report_service,
            employee_service, analytics_service, export_data_service
        )
    elif object_type in ("evaluations", "evaluation"):
        return await _export_evaluation_excel(
            organization_name, object_id, excel_report_service,
            analytics_service, evaluation_service, evaluation_type_service,
            employee_service, criterion_service, criterion_set_service,
            export_data_service
        )
    elif object_type in ("criteria", "criterion"):
        return await _export_criterion_excel(
            organization_name, object_id, excel_report_service,
            criterion_service, analytics_service, criterion_set_service,
            export_data_service
        )
    elif object_type in ("criterion_sets", "criterion_set"):
        return await _export_criterion_set_excel(
            organization_name, object_id, excel_report_service,
            criterion_set_service, criterion_service, analytics_service,
            export_data_service
        )
    else:
        return None


@inject
async def on_export_object_excel(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    excel_report_service: ExcelReportService = Provide[Container.excel_report_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
    analytics_service: AnalyticsService = Provide[Container.analytics_service],
    criterion_service: CriterionService = Provide[Container.criterion_service],
    criterion_set_service: CriterionSetService = Provide[
        Container.criterion_set_service
    ],
    evaluation_service: EvaluationService = Provide[Container.evaluation_service],
    evaluation_type_service: EvaluationTypeService = Provide[
        Container.evaluation_type_service
    ],
    export_data_service: ExportDataService = Provide[Container.export_data_service],
):
    """Export object to Excel.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        excel_report_service: Excel report service instance (injected).
        employee_service: Employee service instance (injected).
        organization_service: Organization service instance (injected).
        analytics_service: Analytics service instance (injected).
        criterion_service: Criterion service instance (injected).
        criterion_set_service: Criterion set service instance (injected).
    """
    await callback.answer("Генерация Excel...")

    # Validate parameters
    is_valid, organization_id, object_id, object_type = await _validate_export_params(
        dialog_manager, callback
    )
    if not is_valid:
        return

    try:
        # Получаем данные организации
        if not isinstance(organization_id, int):
            await callback.answer("❌ Ошибка: некорректный ID организации", show_alert=True)
            return

        organization = await organization_service.get_by_id(organization_id)
        if not organization:
            await callback.answer("❌ Организация не найдена", show_alert=True)
            return

        # Get bot instance
        bot = dialog_manager.middleware_data.get("bot")
        if not bot and dialog_manager.event:
            bot = getattr(dialog_manager.event, "bot", None)

        if not bot or not isinstance(bot, Bot) or not callback.from_user:
            await callback.answer("❌ Ошибка получения бота", show_alert=True)
            return

        # Validate required parameters
        if not isinstance(object_id, int) or not isinstance(object_type, str):
            await callback.answer("❌ Ошибка: некорректные параметры объекта", show_alert=True)
            return

        # Generate Excel report
        excel_path = await _generate_excel_report(
            organization.name, object_id, object_type,
            excel_report_service, analytics_service, evaluation_service,
            evaluation_type_service, employee_service, criterion_service,
            criterion_set_service, export_data_service
        )

        if not excel_path:
            await callback.answer("❌ Не удалось сгенерировать Excel", show_alert=True)
            return

        # Send file to user
        await _send_export_file(bot, callback, excel_path, object_type, object_id, "Excel")

    except Exception as e:
        logger.error(f"Error exporting object to Excel: {e}", exc_info=True)
        await callback.answer(f"❌ Ошибка при экспорте: {str(e)}", show_alert=True)


@inject
async def on_delete_evaluation_from_analytics(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    evaluation_service: EvaluationService = Provide[Container.evaluation_service],
):
    """Handle delete evaluation button click from analytics object detail.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        evaluation_service: Evaluation service instance (injected).
    """
    object_type = dialog_manager.dialog_data.get("object_type")
    object_id = dialog_manager.dialog_data.get("selected_object_id")
    
    # Check if this is an evaluation
    if object_type not in ("evaluations", "evaluation"):
        await callback.answer("❌ Удаление доступно только для замеров", show_alert=True)
        return
    
    if not object_id:
        await callback.answer("❌ Замер не выбран", show_alert=True)
        return
    
    try:
        # Delete the evaluation
        success = await evaluation_service.delete(object_id)
        
        if success:
            await callback.answer("✅ Замер успешно удален", show_alert=True)
            # Return to objects list
            await dialog_manager.switch_to(AnalyticsDialog.objects_list)
        else:
            await callback.answer("❌ Не удалось удалить замер", show_alert=True)
    except Exception as e:
        logger.error(f"Error deleting evaluation {object_id}: {e}", exc_info=True)
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)
