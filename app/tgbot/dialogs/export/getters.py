"""Getters for export dialog."""

from aiogram_dialog import DialogManager

from app.internal.services.presentation_percent import format_percent


async def get_export_data(
    dialog_manager: DialogManager,
    *args,
    **kwargs,
):
    """Get data for export window.

    Args:
        dialog_manager: Dialog manager instance.

    Returns:
        Dictionary with export window data.
    """
    # Copy start_data to dialog_data if not done yet
    start_data = dialog_manager.start_data or {}
    data = dialog_manager.dialog_data

    if start_data and not data.get("evaluation_id"):
        for key, value in start_data.items():
            data[key] = value

    pdf_generated = data.get("pdf_generated", False)
    excel_generated = data.get("excel_generated", False)
    both_generated = pdf_generated and excel_generated

    score_percentage = data.get("score_percentage", 0.0)
    evaluation_id = data.get("evaluation_id")

    # Build message text
    if both_generated:
        message_text = (
            f"✅ <b>Оценка #{evaluation_id}</b>\n\n"
            f"📊 Результат: <b>{format_percent(score_percentage)}</b>\n\n"
            f"Отчёты сгенерированы:\n"
            f"✅ PDF отчёт\n"
            f"✅ Excel отчёт"
        )
    elif pdf_generated:
        message_text = (
            f"✅ <b>Оценка #{evaluation_id}</b>\n\n"
            f"📊 Результат: <b>{format_percent(score_percentage)}</b>\n\n"
            f"✅ PDF отчёт отправлен\n\n"
            f"Хотите также сгенерировать Excel?"
        )
    elif excel_generated:
        message_text = (
            f"✅ <b>Оценка #{evaluation_id}</b>\n\n"
            f"📊 Результат: <b>{format_percent(score_percentage)}</b>\n\n"
            f"✅ Excel отчёт отправлен\n\n"
            f"Хотите также сгенерировать PDF?"
        )
    else:
        message_text = (
            f"✅ <b>Оценка успешно сохранена!</b>\n\n"
            f"📊 Результат: <b>{format_percent(score_percentage)}</b>\n"
            f"🆔 ID оценки: {evaluation_id}\n\n"
            f"Выберите формат для экспорта:"
        )

    return {
        "message_text": message_text,
        "pdf_generated": pdf_generated,
        "excel_generated": excel_generated,
        "both_generated": both_generated,
        "show_pdf_button": not pdf_generated,
        "show_excel_button": not excel_generated,
    }
