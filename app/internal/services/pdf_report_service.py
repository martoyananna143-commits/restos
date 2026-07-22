"""PDF Report Service for generating evaluation reports."""

import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)


class PDFReportService:
    """Service for generating PDF reports from evaluation data."""

    def __init__(self, templates_dir: Optional[Path] = None):
        """Initialize PDF report service.

        Args:
            templates_dir: Optional directory for HTML templates. If None, uses inline template.
        """
        self.templates_dir = templates_dir
        self._register_fonts()

    def _register_fonts(self):
        """Register fonts with Cyrillic support."""
        try:
            # ReportLab включает DejaVu шрифты
            pdfmetrics.registerFont(TTFont('DejaVuSans', 'DejaVuSans.ttf'))
            pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', 'DejaVuSans-Bold.ttf'))
        except Exception as e:
            logger.warning(f"Could not register DejaVu fonts: {e}")
            # Fallback to default fonts

    def generate_evaluation_report(
        self,
        evaluation_id: int,
        evaluation_type_name: str,
        organization_name: str,
        evaluated_employee_name: str,
        filled_by_employee_name: str,
        evaluation_date: str,
        criteria: List[Dict],
        total_criteria: int,
        passed_criteria: int,
        failed_criteria: int,
        score_percentage: float,
        criterion_set_name: Optional[str] = None,
        boolean_criteria_count: Optional[int] = None,
    ) -> Path:
        """Generate PDF report for evaluation.

        Args:
            evaluation_id: Evaluation ID.
            evaluation_type_name: Name of evaluation type.
            organization_name: Name of organization.
            evaluated_employee_name: Name of evaluated employee.
            filled_by_employee_name: Name of employee who filled the evaluation.
            evaluation_date: Date of evaluation.
            criteria: List of criteria with answers and comments.
            total_criteria: Total number of criteria.
            passed_criteria: Number of passed criteria.
            failed_criteria: Number of failed criteria.
            score_percentage: Percentage of successful criteria.
            criterion_set_name: Optional name of criterion set.

        Returns:
            Path to generated PDF file.
        """
        try:
            temp_dir = Path(tempfile.gettempdir())
            pdf_filename = f"evaluation_report_{evaluation_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            pdf_path = temp_dir / pdf_filename

            # Создаём PDF документ
            doc = SimpleDocTemplate(
                str(pdf_path),
                pagesize=A4,
                rightMargin=2*cm,
                leftMargin=2*cm,
                topMargin=2*cm,
                bottomMargin=2*cm
            )

            # Создаём стили
            styles = getSampleStyleSheet()
            
            # Стиль заголовка
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontName='DejaVuSans-Bold',
                fontSize=24,
                textColor=colors.HexColor('#2c3e50'),
                alignment=TA_CENTER,
                spaceAfter=12
            )
            
            # Стиль подзаголовка
            subtitle_style = ParagraphStyle(
                'CustomSubtitle',
                parent=styles['Normal'],
                fontName='DejaVuSans',
                fontSize=14,
                textColor=colors.HexColor('#7f8c8d'),
                alignment=TA_CENTER,
                spaceAfter=6
            )
            
            # Стиль для обычного текста
            normal_style = ParagraphStyle(
                'CustomNormal',
                parent=styles['Normal'],
                fontName='DejaVuSans',
                fontSize=11,
                textColor=colors.HexColor('#333333')
            )
            
            # Стиль для жирного текста
            bold_style = ParagraphStyle(
                'CustomBold',
                parent=styles['Normal'],
                fontName='DejaVuSans-Bold',
                fontSize=11,
                textColor=colors.HexColor('#555555')
            )

            # Собираем элементы документа
            story = []

            # Заголовок
            story.append(Paragraph("Отчет об оценке", title_style))
            story.append(Paragraph(evaluation_type_name, subtitle_style))
            story.append(Paragraph(f"Дата формирования: {datetime.now().strftime('%d.%m.%Y %H:%M')}", subtitle_style))
            story.append(Spacer(1, 1*cm))

            # Информационная секция
            info_data = [
                [Paragraph("<b>Организация:</b>", bold_style), Paragraph(organization_name, normal_style)],
                [Paragraph("<b>Оцениваемый сотрудник:</b>", bold_style), Paragraph(evaluated_employee_name, normal_style)],
                [Paragraph("<b>Оценивающий сотрудник:</b>", bold_style), Paragraph(filled_by_employee_name, normal_style)],
            ]
            
            if criterion_set_name:
                info_data.append([
                    Paragraph("<b>Набор критериев:</b>", bold_style),
                    Paragraph(criterion_set_name, normal_style)
                ])
            
            info_data.append([
                Paragraph("<b>Дата оценки:</b>", bold_style),
                Paragraph(evaluation_date, normal_style)
            ])

            info_table = Table(info_data, colWidths=[5*cm, 11*cm])
            info_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
                ('LEFTPADDING', (0, 0), (-1, -1), 12),
                ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LINEABOVE', (0, 0), (-1, 0), 4, colors.HexColor('#4CAF50')),
            ]))
            story.append(info_table)
            story.append(Spacer(1, 1*cm))

            # Таблица критериев
            criteria_data = [[
                Paragraph("<b>№</b>", bold_style),
                Paragraph("<b>Критерий</b>", bold_style),
                Paragraph("<b>Результат</b>", bold_style),
                Paragraph("<b>Комментарий</b>", bold_style)
            ]]

            for idx, criterion in enumerate(criteria, 1):
                value = criterion.get('value')
                value_type = criterion.get('value_type', 'boolean')
                
                # Парсим JSON строки, если значение - строка с JSON
                if isinstance(value, str):
                    value_stripped = value.strip()
                    if value_stripped.startswith('{') and value_stripped.endswith('}'):
                        try:
                            import json
                            parsed = json.loads(value)
                            if isinstance(parsed, dict) and "value" in parsed:
                                # Извлекаем значение из JSON объекта {"type": "...", "value": ...}
                                extracted_value = parsed.get("value")
                                if extracted_value is not None:
                                    # Преобразуем тип в зависимости от type в JSON
                                    value_type_from_json = parsed.get("type")
                                    if value_type_from_json == "boolean":
                                        value = bool(extracted_value) if not isinstance(extracted_value, bool) else extracted_value
                                    elif value_type_from_json == "number":
                                        if isinstance(extracted_value, str):
                                            try:
                                                value = float(extracted_value) if "." in extracted_value else int(extracted_value)
                                            except (ValueError, TypeError):
                                                value = extracted_value
                                        else:
                                            value = extracted_value
                                    elif value_type_from_json == "string":
                                        value = str(extracted_value)
                                    else:
                                        value = extracted_value
                        except (json.JSONDecodeError, TypeError, ValueError):
                            # Если не удалось распарсить, используем как есть
                            pass
                
                # Форматируем результат в зависимости от типа критерия
                if value_type == 'boolean':
                    # Булевые критерии: Да/Нет с цветом
                    if isinstance(value, bool):
                        is_passed = value
                    elif isinstance(value, str):
                        is_passed = value.lower() in ('true', '1', 'yes', 'да')
                    elif isinstance(value, (int, float)):
                        is_passed = bool(value)
                    else:
                        is_passed = False
                    
                    result_text = "Да" if is_passed else "Нет"
                    text_color = '#155724' if is_passed else '#721c24'
                    result_paragraph = Paragraph(f'<font color="{text_color}"><b>{result_text}</b></font>', normal_style)
                elif value_type == 'string':
                    # Строковые критерии: показываем текст
                    if value is None:
                        result_text = "—"
                    else:
                        result_text = str(value)
                    result_paragraph = Paragraph(f'<b>{result_text}</b>', normal_style)
                elif value_type == 'number':
                    # Числовые критерии: показываем число
                    if value is None:
                        result_text = "—"
                    else:
                        # Форматируем число (убираем лишние нули для float)
                        if isinstance(value, float):
                            result_text = f"{value:.2f}".rstrip('0').rstrip('.')
                        else:
                            result_text = str(value)
                    result_paragraph = Paragraph(f'<b>{result_text}</b>', normal_style)
                else:
                    # Неизвестный тип - показываем как есть
                    result_text = str(value) if value is not None else "—"
                    result_paragraph = Paragraph(f'<b>{result_text}</b>', normal_style)
                
                comment = criterion.get('comment', '—')
                if not comment:
                    comment = '—'
                
                criteria_data.append([
                    Paragraph(str(idx), normal_style),
                    Paragraph(f"<b>{criterion['name']}</b>", normal_style),
                    result_paragraph,
                    Paragraph(f'<i>{comment}</i>', normal_style)
                ])

            criteria_table = Table(criteria_data, colWidths=[1*cm, 6*cm, 3*cm, 6*cm])
            criteria_table.setStyle(TableStyle([
                # Заголовок
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4CAF50')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'DejaVuSans-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 11),
                ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
                
                # Тело таблицы
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#333333')),
                ('FONTNAME', (0, 1), (-1, -1), 'DejaVuSans'),
                ('FONTSIZE', (0, 1), (-1, -1), 10),
                ('ALIGN', (0, 1), (0, -1), 'CENTER'),
                
                # Границы
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#ddd')),
                ('LINEBELOW', (0, 0), (-1, 0), 2, colors.HexColor('#4CAF50')),
                
                # Отступы
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                
                # Чередующиеся строки
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
            ]))
            story.append(criteria_table)
            story.append(Spacer(1, 1*cm))

            # Итоговая статистика
            summary_style = ParagraphStyle(
                'Summary',
                parent=styles['Heading2'],
                fontName='DejaVuSans-Bold',
                fontSize=16,
                textColor=colors.HexColor('#2c3e50'),
                spaceAfter=12
            )
            
            story.append(Paragraph("Итоговая статистика", summary_style))
            
            # Если есть булевые критерии, показываем статистику по ним
            if boolean_criteria_count and boolean_criteria_count > 0:
                summary_data = [[
                    Paragraph(f"<b><font size=18>{total_criteria}</font></b><br/><font size=9>Всего критериев</font>", normal_style),
                    Paragraph(f"<b><font size=18 color='#28a745'>{passed_criteria}</font></b><br/><font size=9>Пройдено (булевые)</font>", normal_style),
                    Paragraph(f"<b><font size=18 color='#dc3545'>{failed_criteria}</font></b><br/><font size=9>Не пройдено (булевые)</font>", normal_style),
                    Paragraph(f"<b><font size=18 color='#4CAF50'>{score_percentage:.1f}%</font></b><br/><font size=9>Успешность (булевые)</font>", normal_style),
                ]]
                
                summary_table = Table(summary_data, colWidths=[4*cm, 4*cm, 4*cm, 4*cm])
                summary_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#e8f5e9')),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 12),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                    ('TOPPADDING', (0, 0), (-1, -1), 15),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
                    ('LINEABOVE', (0, 0), (-1, 0), 4, colors.HexColor('#4CAF50')),
                ]))
                story.append(summary_table)
                story.append(Spacer(1, 0.5*cm))
                
                # Текст статистики с указанием, что это только для булевых критериев
                non_boolean_count = total_criteria - boolean_criteria_count
                if non_boolean_count > 0:
                    summary_text = (
                        f"<b>Статистика по булевым критериям:</b> {passed_criteria} из {boolean_criteria_count} "
                        f"критериев пройдено успешно. Процент успешных ответов составляет {score_percentage:.1f}%.<br/>"
                        f"<i>Примечание: {non_boolean_count} критериев (текстовые и числовые) не учитываются в статистике, "
                        f"так как их невозможно оценить по принципу верно/неверно.</i>"
                    )
                else:
                    summary_text = (
                        f"<b>Общая оценка:</b> {passed_criteria} из {total_criteria} критериев пройдено успешно. "
                        f"Процент успешных ответов составляет {score_percentage:.1f}%."
                    )
            else:
                # Если нет булевых критериев, показываем только общее количество
                summary_data = [[
                    Paragraph(f"<b><font size=18>{total_criteria}</font></b><br/><font size=9>Всего критериев</font>", normal_style),
                ]]
                
                summary_table = Table(summary_data, colWidths=[16*cm])
                summary_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#e8f5e9')),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 12),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                    ('TOPPADDING', (0, 0), (-1, -1), 15),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
                    ('LINEABOVE', (0, 0), (-1, 0), 4, colors.HexColor('#4CAF50')),
                ]))
                story.append(summary_table)
                story.append(Spacer(1, 0.5*cm))
                
                summary_text = (
                    f"<b>Всего критериев:</b> {total_criteria}.<br/>"
                    f"<i>Примечание: в данной оценке используются только текстовые и числовые критерии, "
                    f"которые невозможно оценить по принципу верно/неверно.</i>"
                )
            
            story.append(Paragraph(summary_text, normal_style))
            story.append(Spacer(1, 1*cm))

            # Футер
            footer_style = ParagraphStyle(
                'Footer',
                parent=styles['Normal'],
                fontName='DejaVuSans',
                fontSize=9,
                textColor=colors.HexColor('#7f8c8d'),
                alignment=TA_CENTER
            )
            story.append(Spacer(1, 1*cm))
            story.append(Paragraph("Автоматически сгенерированный отчет", footer_style))
            story.append(Paragraph(f"ID оценки: #{evaluation_id}", footer_style))

            doc.build(story)

            logger.info(f"PDF report generated: {pdf_path}")
            return pdf_path

        except Exception as e:
            logger.error(f"Error generating PDF report: {str(e)}", exc_info=True)
            raise

    def generate_employee_report(
        self,
        employee_id: int,
        employee_name: str,
        organization_name: str,
        position: Optional[str] = None,
        phone: Optional[str] = None,
        telegram_id: Optional[int] = None,
        username: Optional[str] = None,
        hire_date: Optional[str] = None,
        is_active: bool = True,
        total_evaluations: int = 0,
        avg_score: Optional[float] = None,
        best_score: Optional[float] = None,
        worst_score: Optional[float] = None,
        last_evaluation_date: Optional[str] = None,
    ) -> Path:
        """Generate PDF report for employee.
        
        Args:
            employee_id: Employee ID.
            employee_name: Employee full name.
            organization_name: Organization name.
            position: Employee position.
            phone: Employee phone.
            telegram_id: Employee Telegram ID.
            username: Employee username.
            hire_date: Employee hire date.
            is_active: Whether employee is active.
            total_evaluations: Total number of evaluations.
            avg_score: Average score.
            best_score: Best score.
            worst_score: Worst score.
            last_evaluation_date: Last evaluation date.
            
        Returns:
            Path to generated PDF file.
        """
        try:
            temp_dir = Path(tempfile.gettempdir())
            pdf_filename = f"employee_report_{employee_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            pdf_path = temp_dir / pdf_filename

            doc = SimpleDocTemplate(
                str(pdf_path),
                pagesize=A4,
                rightMargin=2*cm,
                leftMargin=2*cm,
                topMargin=2*cm,
                bottomMargin=2*cm
            )

            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontName='DejaVuSans-Bold',
                fontSize=24,
                textColor=colors.HexColor('#2c3e50'),
                alignment=TA_CENTER,
                spaceAfter=12
            )
            subtitle_style = ParagraphStyle(
                'CustomSubtitle',
                parent=styles['Normal'],
                fontName='DejaVuSans',
                fontSize=14,
                textColor=colors.HexColor('#7f8c8d'),
                alignment=TA_CENTER,
                spaceAfter=6
            )
            normal_style = ParagraphStyle(
                'CustomNormal',
                parent=styles['Normal'],
                fontName='DejaVuSans',
                fontSize=11,
                textColor=colors.HexColor('#333333')
            )
            bold_style = ParagraphStyle(
                'CustomBold',
                parent=styles['Normal'],
                fontName='DejaVuSans-Bold',
                fontSize=11,
                textColor=colors.HexColor('#555555')
            )

            story = []

            # Заголовок
            story.append(Paragraph("Отчет по сотруднику", title_style))
            story.append(Paragraph(f"Дата формирования: {datetime.now().strftime('%d.%m.%Y %H:%M')}", subtitle_style))
            story.append(Spacer(1, 1*cm))

            # Информация о сотруднике
            info_data = [
                [Paragraph("<b>Организация:</b>", bold_style), Paragraph(organization_name, normal_style)],
                [Paragraph("<b>ФИО:</b>", bold_style), Paragraph(employee_name, normal_style)],
            ]
            
            if position:
                info_data.append([Paragraph("<b>Должность:</b>", bold_style), Paragraph(position, normal_style)])
            if phone:
                info_data.append([Paragraph("<b>Телефон:</b>", bold_style), Paragraph(phone, normal_style)])
            if telegram_id:
                info_data.append([Paragraph("<b>Telegram ID:</b>", bold_style), Paragraph(str(telegram_id), normal_style)])
            if username:
                info_data.append([Paragraph("<b>Username:</b>", bold_style), Paragraph(username, normal_style)])
            if hire_date:
                info_data.append([Paragraph("<b>Дата найма:</b>", bold_style), Paragraph(hire_date, normal_style)])
            
            info_data.append([Paragraph("<b>Статус:</b>", bold_style), Paragraph("Активен" if is_active else "Неактивен", normal_style)])

            info_table = Table(info_data, colWidths=[5*cm, 11*cm])
            info_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
                ('LEFTPADDING', (0, 0), (-1, -1), 12),
                ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LINEABOVE', (0, 0), (-1, 0), 4, colors.HexColor('#4CAF50')),
            ]))
            story.append(info_table)
            story.append(Spacer(1, 1*cm))

            # Статистика
            summary_style = ParagraphStyle(
                'Summary',
                parent=styles['Heading2'],
                fontName='DejaVuSans-Bold',
                fontSize=16,
                textColor=colors.HexColor('#2c3e50'),
                spaceAfter=12
            )
            story.append(Paragraph("Статистика по замерам", summary_style))
            
            stats_data = [[
                Paragraph(f"<b><font size=18>{total_evaluations}</font></b><br/><font size=9>Всего замеров</font>", normal_style),
            ]]
            
            if avg_score is not None:
                stats_data[0].append(Paragraph(f"<b><font size=18 color='#4CAF50'>{avg_score:.1f}%</font></b><br/><font size=9>Средний балл</font>", normal_style))
            if best_score is not None:
                stats_data[0].append(Paragraph(f"<b><font size=18 color='#28a745'>{best_score:.1f}%</font></b><br/><font size=9>Лучший результат</font>", normal_style))
            if worst_score is not None:
                stats_data[0].append(Paragraph(f"<b><font size=18 color='#dc3545'>{worst_score:.1f}%</font></b><br/><font size=9>Худший результат</font>", normal_style))
            
            if len(stats_data[0]) > 1:
                stats_table = Table(stats_data, colWidths=[4*cm] * len(stats_data[0]))
            else:
                stats_table = Table(stats_data, colWidths=[16*cm])
            
            stats_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#e8f5e9')),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 12),
                ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                ('TOPPADDING', (0, 0), (-1, -1), 15),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
                ('LINEABOVE', (0, 0), (-1, 0), 4, colors.HexColor('#4CAF50')),
            ]))
            story.append(stats_table)
            
            if last_evaluation_date:
                story.append(Spacer(1, 0.5*cm))
                story.append(Paragraph(f"<b>Последний замер:</b> {last_evaluation_date}", normal_style))
            
            story.append(Spacer(1, 1*cm))

            # Футер
            footer_style = ParagraphStyle(
                'Footer',
                parent=styles['Normal'],
                fontName='DejaVuSans',
                fontSize=9,
                textColor=colors.HexColor('#7f8c8d'),
                alignment=TA_CENTER
            )
            story.append(Spacer(1, 1*cm))
            story.append(Paragraph("Автоматически сгенерированный отчет", footer_style))
            story.append(Paragraph(f"ID сотрудника: #{employee_id}", footer_style))

            doc.build(story)
            logger.info(f"PDF employee report generated: {pdf_path}")
            return pdf_path

        except Exception as e:
            logger.error(f"Error generating employee PDF report: {str(e)}", exc_info=True)
            raise

    def generate_criterion_report(
        self,
        criterion_id: int,
        criterion_name: str,
        organization_name: str,
        code: str,
        value_type: str,
        evaluation_type_id: int,
        category_id: Optional[int] = None,
        is_required: bool = False,
        is_active: bool = True,
        description: Optional[str] = None,
        sort_order: int = 0,
        usage_count: int = 0,
        criterion_sets: Optional[List[str]] = None,
    ) -> Path:
        """Generate PDF report for criterion.
        
        Args:
            criterion_id: Criterion ID.
            criterion_name: Criterion name.
            organization_name: Organization name.
            code: Criterion code.
            value_type: Criterion value type (boolean, string, number).
            evaluation_type_id: Evaluation type ID.
            category_id: Category ID.
            is_required: Whether criterion is required.
            is_active: Whether criterion is active.
            description: Criterion description.
            sort_order: Sort order.
            usage_count: Number of evaluations using this criterion.
            criterion_sets: List of criterion set names using this criterion.
            
        Returns:
            Path to generated PDF file.
        """
        try:
            temp_dir = Path(tempfile.gettempdir())
            pdf_filename = f"criterion_report_{criterion_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            pdf_path = temp_dir / pdf_filename

            doc = SimpleDocTemplate(
                str(pdf_path),
                pagesize=A4,
                rightMargin=2*cm,
                leftMargin=2*cm,
                topMargin=2*cm,
                bottomMargin=2*cm
            )

            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontName='DejaVuSans-Bold',
                fontSize=24,
                textColor=colors.HexColor('#2c3e50'),
                alignment=TA_CENTER,
                spaceAfter=12
            )
            subtitle_style = ParagraphStyle(
                'CustomSubtitle',
                parent=styles['Normal'],
                fontName='DejaVuSans',
                fontSize=14,
                textColor=colors.HexColor('#7f8c8d'),
                alignment=TA_CENTER,
                spaceAfter=6
            )
            normal_style = ParagraphStyle(
                'CustomNormal',
                parent=styles['Normal'],
                fontName='DejaVuSans',
                fontSize=11,
                textColor=colors.HexColor('#333333')
            )
            bold_style = ParagraphStyle(
                'CustomBold',
                parent=styles['Normal'],
                fontName='DejaVuSans-Bold',
                fontSize=11,
                textColor=colors.HexColor('#555555')
            )

            story = []

            # Заголовок
            story.append(Paragraph("Отчет по критерию", title_style))
            story.append(Paragraph(f"Дата формирования: {datetime.now().strftime('%d.%m.%Y %H:%M')}", subtitle_style))
            story.append(Spacer(1, 1*cm))

            # Информация о критерии
            info_data = [
                [Paragraph("<b>Организация:</b>", bold_style), Paragraph(organization_name, normal_style)],
                [Paragraph("<b>Название:</b>", bold_style), Paragraph(criterion_name, normal_style)],
                [Paragraph("<b>Код:</b>", bold_style), Paragraph(code, normal_style)],
                [Paragraph("<b>Тип значения:</b>", bold_style), Paragraph(value_type, normal_style)],
                [Paragraph("<b>Тип оценки ID:</b>", bold_style), Paragraph(str(evaluation_type_id), normal_style)],
                [Paragraph("<b>Категория ID:</b>", bold_style), Paragraph(str(category_id) if category_id else "Нет", normal_style)],
                [Paragraph("<b>Обязательный:</b>", bold_style), Paragraph("Да" if is_required else "Нет", normal_style)],
                [Paragraph("<b>Активен:</b>", bold_style), Paragraph("Да" if is_active else "Нет", normal_style)],
                [Paragraph("<b>Порядок сортировки:</b>", bold_style), Paragraph(str(sort_order), normal_style)],
            ]
            
            if description:
                info_data.append([Paragraph("<b>Описание:</b>", bold_style), Paragraph(description, normal_style)])

            info_table = Table(info_data, colWidths=[5*cm, 11*cm])
            info_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
                ('LEFTPADDING', (0, 0), (-1, -1), 12),
                ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LINEABOVE', (0, 0), (-1, 0), 4, colors.HexColor('#4CAF50')),
            ]))
            story.append(info_table)
            story.append(Spacer(1, 1*cm))

            # Статистика использования
            summary_style = ParagraphStyle(
                'Summary',
                parent=styles['Heading2'],
                fontName='DejaVuSans-Bold',
                fontSize=16,
                textColor=colors.HexColor('#2c3e50'),
                spaceAfter=12
            )
            story.append(Paragraph("Статистика использования", summary_style))
            
            stats_data = [[
                Paragraph(f"<b><font size=18>{usage_count}</font></b><br/><font size=9>Использован в замерах</font>", normal_style),
            ]]
            
            stats_table = Table(stats_data, colWidths=[16*cm])
            stats_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#e8f5e9')),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 12),
                ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                ('TOPPADDING', (0, 0), (-1, -1), 15),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
                ('LINEABOVE', (0, 0), (-1, 0), 4, colors.HexColor('#4CAF50')),
            ]))
            story.append(stats_table)
            story.append(Spacer(1, 0.5*cm))
            
            if criterion_sets:
                story.append(Paragraph(f"<b>Входит в наборы ({len(criterion_sets)}):</b>", bold_style))
                for set_name in criterion_sets[:20]:  # Показываем первые 20
                    story.append(Paragraph(f"  • {set_name}", normal_style))
                if len(criterion_sets) > 20:
                    story.append(Paragraph(f"  ... и еще {len(criterion_sets) - 20}", normal_style))
            else:
                story.append(Paragraph("Входит в наборы: Нет", normal_style))
            
            story.append(Spacer(1, 1*cm))

            # Футер
            footer_style = ParagraphStyle(
                'Footer',
                parent=styles['Normal'],
                fontName='DejaVuSans',
                fontSize=9,
                textColor=colors.HexColor('#7f8c8d'),
                alignment=TA_CENTER
            )
            story.append(Spacer(1, 1*cm))
            story.append(Paragraph("Автоматически сгенерированный отчет", footer_style))
            story.append(Paragraph(f"ID критерия: #{criterion_id}", footer_style))

            doc.build(story)
            logger.info(f"PDF criterion report generated: {pdf_path}")
            return pdf_path

        except Exception as e:
            logger.error(f"Error generating criterion PDF report: {str(e)}", exc_info=True)
            raise

    def generate_criterion_set_report(
        self,
        criterion_set_id: int,
        criterion_set_name: str,
        organization_name: str,
        is_default: bool = False,
        is_active: bool = True,
        description: Optional[str] = None,
        criteria: Optional[List[Dict]] = None,
        usage_count: int = 0,
    ) -> Path:
        """Generate PDF report for criterion set.
        
        Args:
            criterion_set_id: Criterion set ID.
            criterion_set_name: Criterion set name.
            organization_name: Organization name.
            is_default: Whether set is default.
            is_active: Whether set is active.
            description: Set description.
            criteria: List of criteria in the set.
            usage_count: Number of evaluations using this set.
            
        Returns:
            Path to generated PDF file.
        """
        try:
            temp_dir = Path(tempfile.gettempdir())
            pdf_filename = f"criterion_set_report_{criterion_set_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            pdf_path = temp_dir / pdf_filename

            doc = SimpleDocTemplate(
                str(pdf_path),
                pagesize=A4,
                rightMargin=2*cm,
                leftMargin=2*cm,
                topMargin=2*cm,
                bottomMargin=2*cm
            )

            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontName='DejaVuSans-Bold',
                fontSize=24,
                textColor=colors.HexColor('#2c3e50'),
                alignment=TA_CENTER,
                spaceAfter=12
            )
            subtitle_style = ParagraphStyle(
                'CustomSubtitle',
                parent=styles['Normal'],
                fontName='DejaVuSans',
                fontSize=14,
                textColor=colors.HexColor('#7f8c8d'),
                alignment=TA_CENTER,
                spaceAfter=6
            )
            normal_style = ParagraphStyle(
                'CustomNormal',
                parent=styles['Normal'],
                fontName='DejaVuSans',
                fontSize=11,
                textColor=colors.HexColor('#333333')
            )
            bold_style = ParagraphStyle(
                'CustomBold',
                parent=styles['Normal'],
                fontName='DejaVuSans-Bold',
                fontSize=11,
                textColor=colors.HexColor('#555555')
            )

            story = []

            # Заголовок
            story.append(Paragraph("Отчет по набору критериев", title_style))
            story.append(Paragraph(f"Дата формирования: {datetime.now().strftime('%d.%m.%Y %H:%M')}", subtitle_style))
            story.append(Spacer(1, 1*cm))

            # Информация о наборе
            info_data = [
                [Paragraph("<b>Организация:</b>", bold_style), Paragraph(organization_name, normal_style)],
                [Paragraph("<b>Название:</b>", bold_style), Paragraph(criterion_set_name, normal_style)],
                [Paragraph("<b>Дефолтный:</b>", bold_style), Paragraph("Да" if is_default else "Нет", normal_style)],
                [Paragraph("<b>Активен:</b>", bold_style), Paragraph("Да" if is_active else "Нет", normal_style)],
            ]
            
            if description:
                info_data.append([Paragraph("<b>Описание:</b>", bold_style), Paragraph(description, normal_style)])

            info_table = Table(info_data, colWidths=[5*cm, 11*cm])
            info_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
                ('LEFTPADDING', (0, 0), (-1, -1), 12),
                ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LINEABOVE', (0, 0), (-1, 0), 4, colors.HexColor('#4CAF50')),
            ]))
            story.append(info_table)
            story.append(Spacer(1, 1*cm))

            # Критерии в наборе
            if criteria:
                criteria_style = ParagraphStyle(
                    'Criteria',
                    parent=styles['Heading2'],
                    fontName='DejaVuSans-Bold',
                    fontSize=16,
                    textColor=colors.HexColor('#2c3e50'),
                    spaceAfter=12
                )
                story.append(Paragraph(f"Критерии в наборе ({len(criteria)})", criteria_style))
                
                criteria_data = [[
                    Paragraph("<b>№</b>", bold_style),
                    Paragraph("<b>Название</b>", bold_style),
                    Paragraph("<b>Код</b>", bold_style),
                    Paragraph("<b>Тип</b>", bold_style)
                ]]
                
                for idx, criterion in enumerate(criteria[:50], 1):  # Показываем первые 50
                    criteria_data.append([
                        Paragraph(str(idx), normal_style),
                        Paragraph(criterion.get('name', 'N/A'), normal_style),
                        Paragraph(criterion.get('code', 'N/A'), normal_style),
                        Paragraph(criterion.get('value_type', 'N/A'), normal_style),
                    ])
                
                criteria_table = Table(criteria_data, colWidths=[1*cm, 7*cm, 3*cm, 5*cm])
                criteria_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4CAF50')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('FONTNAME', (0, 0), (-1, 0), 'DejaVuSans-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 11),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                    ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#333333')),
                    ('FONTNAME', (0, 1), (-1, -1), 'DejaVuSans'),
                    ('FONTSIZE', (0, 1), (-1, -1), 10),
                    ('ALIGN', (0, 1), (0, -1), 'CENTER'),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#ddd')),
                    ('LINEBELOW', (0, 0), (-1, 0), 2, colors.HexColor('#4CAF50')),
                    ('LEFTPADDING', (0, 0), (-1, -1), 8),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                    ('TOPPADDING', (0, 0), (-1, -1), 8),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
                ]))
                story.append(criteria_table)
                
                if len(criteria) > 50:
                    story.append(Spacer(1, 0.5*cm))
                    story.append(Paragraph(f"<i>... и еще {len(criteria) - 50} критериев</i>", normal_style))
                
                story.append(Spacer(1, 1*cm))
            else:
                story.append(Paragraph("Критерии в наборе: Нет", normal_style))
                story.append(Spacer(1, 1*cm))

            # Статистика использования
            summary_style = ParagraphStyle(
                'Summary',
                parent=styles['Heading2'],
                fontName='DejaVuSans-Bold',
                fontSize=16,
                textColor=colors.HexColor('#2c3e50'),
                spaceAfter=12
            )
            story.append(Paragraph("Статистика использования", summary_style))
            
            stats_data = [[
                Paragraph(f"<b><font size=18>{usage_count}</font></b><br/><font size=9>Использован в замерах</font>", normal_style),
            ]]
            
            stats_table = Table(stats_data, colWidths=[16*cm])
            stats_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#e8f5e9')),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 12),
                ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                ('TOPPADDING', (0, 0), (-1, -1), 15),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
                ('LINEABOVE', (0, 0), (-1, 0), 4, colors.HexColor('#4CAF50')),
            ]))
            story.append(stats_table)
            story.append(Spacer(1, 1*cm))

            # Футер
            footer_style = ParagraphStyle(
                'Footer',
                parent=styles['Normal'],
                fontName='DejaVuSans',
                fontSize=9,
                textColor=colors.HexColor('#7f8c8d'),
                alignment=TA_CENTER
            )
            story.append(Spacer(1, 1*cm))
            story.append(Paragraph("Автоматически сгенерированный отчет", footer_style))
            story.append(Paragraph(f"ID набора: #{criterion_set_id}", footer_style))

            doc.build(story)
            logger.info(f"PDF criterion set report generated: {pdf_path}")
            return pdf_path

        except Exception as e:
            logger.error(f"Error generating criterion set PDF report: {str(e)}", exc_info=True)
            raise