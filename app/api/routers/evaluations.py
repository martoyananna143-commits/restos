"""Evaluations API router."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, StreamingResponse

from app.api.auth import get_current_employee
from app.api.deps import (
    get_criterion_service,
    get_criterion_set_service,
    get_employee_service,
    get_evaluation_service,
    get_excel_report_service,
    get_pdf_report_service,
)
from app.api.schemas import (
    EvaluationCreate,
    EvaluationResponse,
    EvaluationUpdate,
)
from app.infra.database.models.employee.employee import Employee
from app.infra.database.repository.criterion_value.dto import CreateCriterionValueDTO
from app.infra.database.repository.evaluation.dto import (
    CreateEvaluationDTO,
    UpdateEvaluationDTO,
)
from app.internal.services.criterion_service import CriterionService
from app.internal.services.criterion_set_service import CriterionSetService
from app.internal.services.employee_service import EmployeeService
from app.internal.services.evaluation_service import EvaluationService
from app.internal.services.excel_report_service import ExcelReportService
from app.internal.services.pdf_report_service import PDFReportService

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.get("", response_model=List[EvaluationResponse])
async def list_evaluations(
    organization_id: Optional[int] = None,
    employee_id: Optional[int] = None,
    filled_by_employee_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Get evaluations list with filters.
    
    Note: This endpoint currently requires repository extension to support filtering.
    
    Args:
        organization_id: Optional filter by organization ID.
        employee_id: Optional filter by evaluated employee ID.
        filled_by_employee_id: Optional filter by employee who filled evaluation.
        date_from: Optional start date filter.
        date_to: Optional end date filter.
        service: Evaluation service dependency.
        
    Returns:
        List of evaluations.
        
    Raises:
        HTTPException: Method not implemented (requires repository extension).
    """
    # This would require a new repository method to support filtering
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="List evaluations with filters not yet implemented. Use analytics endpoints instead.",
    )


@router.get("/{evaluation_id}", response_model=EvaluationResponse)
async def get_evaluation(
    evaluation_id: int,
    employee: Employee = Depends(get_current_employee),
    service: EvaluationService = Depends(get_evaluation_service),
    employee_service: EmployeeService = Depends(get_employee_service),
):
    """Get evaluation by ID.
    
    Requires employee access to the evaluation's organization.
    
    Args:
        evaluation_id: Evaluation ID.
        employee: Authenticated employee in organization.
        service: Evaluation service dependency.
        employee_service: Employee service dependency.
        
    Returns:
        Evaluation details.
        
    Raises:
        HTTPException: If evaluation not found or access denied.
    """
    evaluation = await service.get_by_id(evaluation_id)
    if not evaluation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation not found",
        )
    
    # Verify employee has access to evaluation's organization
    filled_by_employee = await employee_service.get_by_id(evaluation.filled_by_employee_id)
    if not filled_by_employee or filled_by_employee.organization_id != employee.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this evaluation",
        )
    
    return evaluation


@router.post("", response_model=EvaluationResponse, status_code=status.HTTP_201_CREATED)
async def create_evaluation(
    data: EvaluationCreate,
    employee: Employee = Depends(get_current_employee),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    employee_service: EmployeeService = Depends(get_employee_service),
    criterion_set_service: CriterionSetService = Depends(get_criterion_set_service),
    criterion_service: CriterionService = Depends(get_criterion_service),
):
    """Create a new evaluation.
    
    Requires employee access to the organization.
    
    Args:
        data: Evaluation creation data.
        employee: Authenticated employee in organization.
        evaluation_service: Evaluation service dependency.
        employee_service: Employee service dependency.
        criterion_set_service: CriterionSet service dependency.
        criterion_service: Criterion service dependency.
        
    Returns:
        Created evaluation.
        
    Raises:
        HTTPException: If validation fails or entities not found or access denied.
    """
    # Verify employees exist
    filled_by_employee = await employee_service.get_by_id(data.filled_by_employee_id)
    if not filled_by_employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Filled by employee not found",
        )
    
    evaluated_employee = await employee_service.get_by_id(data.evaluated_employee_id)
    if not evaluated_employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluated employee not found",
        )
    
    # Verify current employee has access to this organization
    if filled_by_employee.organization_id != employee.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this organization",
        )
    
    # Verify they belong to the same organization
    if filled_by_employee.organization_id != evaluated_employee.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Employees must belong to the same organization",
        )
    
    # Verify cannot evaluate self
    if data.filled_by_employee_id == data.evaluated_employee_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot evaluate self",
        )
    
    # Verify criterion set exists
    criterion_set = await criterion_set_service.get_by_id(data.criterion_set_id)
    if not criterion_set:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Criterion set not found",
        )
    
    # Verify criterion set belongs to same organization
    if criterion_set.organization_id != filled_by_employee.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Criterion set must belong to the same organization",
        )
    
    # Create evaluation DTO
    dto = CreateEvaluationDTO(
        filled_by_employee_id=data.filled_by_employee_id,
        evaluated_employee_id=data.evaluated_employee_id,
        criterion_set_id=data.criterion_set_id,
        evaluation_date=data.evaluation_date,
    )
    
    evaluation = await evaluation_service.create(dto)
    
    # TODO: Create criterion values
    # This requires access to CriterionValue repository which needs to be injected
    
    return evaluation


@router.put("/{evaluation_id}", response_model=EvaluationResponse)
async def update_evaluation(
    evaluation_id: int,
    data: EvaluationUpdate,
    employee: Employee = Depends(get_current_employee),
    service: EvaluationService = Depends(get_evaluation_service),
    employee_service: EmployeeService = Depends(get_employee_service),
):
    """Update evaluation.
    
    Requires employee access to the evaluation's organization.
    
    Args:
        evaluation_id: Evaluation ID.
        data: Evaluation update data.
        employee: Authenticated employee in organization.
        service: Evaluation service dependency.
        employee_service: Employee service dependency.
        
    Returns:
        Updated evaluation.
        
    Raises:
        HTTPException: If evaluation not found or access denied.
    """
    # Get existing evaluation
    existing = await service.get_by_id(evaluation_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation not found",
        )
    
    # Verify employee has access to evaluation's organization
    filled_by_employee = await employee_service.get_by_id(existing.filled_by_employee_id)
    if not filled_by_employee or filled_by_employee.organization_id != employee.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this evaluation",
        )
    
    dto = UpdateEvaluationDTO(
        evaluation_date=data.evaluation_date,
    )
    
    evaluation = await service.update(evaluation_id, dto)
    if not evaluation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation not found",
        )
    
    # TODO: Update criterion values if provided
    
    return evaluation


@router.get("/{evaluation_id}/export/excel")
async def export_evaluation_to_excel(
    evaluation_id: int,
    employee: Employee = Depends(get_current_employee),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    employee_service: EmployeeService = Depends(get_employee_service),
    excel_report_service: ExcelReportService = Depends(get_excel_report_service),
):
    """Export evaluation to Excel file.
    
    Requires employee access to the evaluation's organization.
    
    Args:
        evaluation_id: Evaluation ID.
        employee: Authenticated employee in organization.
        evaluation_service: Evaluation service dependency.
        employee_service: Employee service dependency.
        excel_report_service: Excel report service dependency.
        
    Returns:
        Excel file download.
        
    Raises:
        HTTPException: If evaluation not found or export fails or access denied.
    """
    evaluation = await evaluation_service.get_by_id(evaluation_id)
    if not evaluation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation not found",
        )
    
    # Verify employee has access to evaluation's organization
    filled_by_employee = await employee_service.get_by_id(evaluation.filled_by_employee_id)
    if not filled_by_employee or filled_by_employee.organization_id != employee.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this evaluation",
        )
    
    # This requires implementation in ExcelReportService
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Excel export not yet implemented",
    )


@router.get("/{evaluation_id}/export/pdf")
async def export_evaluation_to_pdf(
    evaluation_id: int,
    employee: Employee = Depends(get_current_employee),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    employee_service: EmployeeService = Depends(get_employee_service),
    pdf_report_service: PDFReportService = Depends(get_pdf_report_service),
):
    """Export evaluation to PDF file.
    
    Requires employee access to the evaluation's organization.
    
    Args:
        evaluation_id: Evaluation ID.
        employee: Authenticated employee in organization.
        evaluation_service: Evaluation service dependency.
        employee_service: Employee service dependency.
        pdf_report_service: PDF report service dependency.
        
    Returns:
        PDF file download.
        
    Raises:
        HTTPException: If evaluation not found or export fails or access denied.
    """
    evaluation = await evaluation_service.get_by_id(evaluation_id)
    if not evaluation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation not found",
        )
    
    # Verify employee has access to evaluation's organization
    filled_by_employee = await employee_service.get_by_id(evaluation.filled_by_employee_id)
    if not filled_by_employee or filled_by_employee.organization_id != employee.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this evaluation",
        )
    
    # This requires implementation in PDFReportService
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="PDF export not yet implemented",
    )
