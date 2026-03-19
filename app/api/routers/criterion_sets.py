"""Criterion Sets API router."""

from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.auth import get_current_employee, require_admin
from app.api.deps import (
    get_criterion_service,
    get_criterion_set_service,
    get_evaluation_type_service,
    get_organization_service,
)
from app.api.schemas import (
    CriterionSetCreate,
    CriterionSetResponse,
    CriterionSetUpdate,
    MessageResponse,
)
from app.infra.database.models.employee.employee import Employee
from app.infra.database.repository.criterion_set.dto import (
    CreateCriterionSetDTO,
    UpdateCriterionSetDTO,
)
from app.internal.usecases.criterion_service import CriterionService
from app.internal.usecases.criterion_set_service import CriterionSetService
from app.internal.usecases.evaluation_type_service import EvaluationTypeService
from app.internal.usecases.organization_service import OrganizationService

router = APIRouter(prefix="/criterion-sets", tags=["criterion-sets"])


@router.get("", response_model=List[CriterionSetResponse])
async def list_criterion_sets(
    organization_id: int,
    include_inactive: bool = False,
    employee: Employee = Depends(get_current_employee),
    service: CriterionSetService = Depends(get_criterion_set_service),
):
    """Get criterion sets list for an organization.
    
    Requires employee access to the organization.
    
    Args:
        organization_id: Organization ID (from X-Organization-Id header).
        include_inactive: Include inactive criterion sets.
        employee: Authenticated employee in organization.
        service: CriterionSet service dependency.
        
    Returns:
        List of criterion sets.
        
    Raises:
        HTTPException: If access denied.
    """
    # Verify employee has access to this organization
    if employee.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this organization",
        )
    
    criterion_sets = await service.get_by_organization_id(organization_id, include_inactive)
    return criterion_sets


@router.get("/{criterion_set_id}", response_model=CriterionSetResponse)
async def get_criterion_set(
    criterion_set_id: int,
    employee: Employee = Depends(get_current_employee),
    service: CriterionSetService = Depends(get_criterion_set_service),
):
    """Get criterion set by ID.
    
    Requires employee access to the criterion set's organization.
    
    Args:
        criterion_set_id: Criterion set ID.
        employee: Authenticated employee in organization.
        service: CriterionSet service dependency.
        
    Returns:
        Criterion set details.
        
    Raises:
        HTTPException: If criterion set not found or access denied.
    """
    criterion_set = await service.get_by_id(criterion_set_id)
    if not criterion_set:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Criterion set not found",
        )
    
    # Verify employee has access to criterion set's organization
    if criterion_set.organization_id != employee.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this criterion set",
        )
    
    return criterion_set


@router.post("", response_model=CriterionSetResponse, status_code=status.HTTP_201_CREATED)
async def create_criterion_set(
    data: CriterionSetCreate,
    employee: Employee = Depends(require_admin),
    criterion_set_service: CriterionSetService = Depends(get_criterion_set_service),
    organization_service: OrganizationService = Depends(get_organization_service),
    criterion_service: CriterionService = Depends(get_criterion_service),
):
    """Create a new criterion set.
    
    Requires administrator access in the organization.
    
    Args:
        data: Criterion set creation data.
        employee: Authenticated admin employee.
        criterion_set_service: CriterionSet service dependency.
        organization_service: Organization service dependency.
        criterion_service: Criterion service dependency.
        
    Returns:
        Created criterion set.
        
    Raises:
        HTTPException: If organization not found or criteria invalid or access denied.
    """
    # Verify admin has access to this organization
    if employee.organization_id != data.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this organization",
        )
    """
    # Verify organization exists
    organization = await organization_service.get_by_id(data.organization_id)
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    
    # Verify criteria exist
    criteria = await criterion_service.get_by_ids(data.criterion_ids)
    if len(criteria) != len(data.criterion_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Some criteria not found",
        )
    
    dto = CreateCriterionSetDTO(
        organization_id=data.organization_id,
        name=data.name,
        description=data.description,
        is_default=data.is_default,
        criterion_ids=data.criterion_ids,
    )
    criterion_set = await criterion_set_service.create(dto)
    return criterion_set


@router.put("/{criterion_set_id}", response_model=CriterionSetResponse)
async def update_criterion_set(
    criterion_set_id: int,
    data: CriterionSetUpdate,
    criterion_set_service: CriterionSetService = Depends(get_criterion_set_service),
    criterion_service: CriterionService = Depends(get_criterion_service),
):
    """Update criterion set.
    
    Args:
        criterion_set_id: Criterion set ID.
        data: Criterion set update data.
        criterion_set_service: CriterionSet service dependency.
        criterion_service: Criterion service dependency.
        
    Returns:
        Updated criterion set.
        
    Raises:
        HTTPException: If criterion set not found or criteria invalid.
    """
    # Verify criterion set exists
    criterion_set = await criterion_set_service.get_by_id(criterion_set_id)
    if not criterion_set:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Criterion set not found",
        )
    
    # Verify criteria exist if provided
    if data.criterion_ids is not None:
        criteria = await criterion_service.get_by_ids(data.criterion_ids)
        if len(criteria) != len(data.criterion_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Some criteria not found",
            )
    
    dto = UpdateCriterionSetDTO(
        name=data.name,
        description=data.description,
        is_default=data.is_default,
        criterion_ids=data.criterion_ids,
    )
    updated_set = await criterion_set_service.update(criterion_set_id, dto)
    if not updated_set:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Criterion set not found",
        )
    return updated_set


@router.delete("/{criterion_set_id}", response_model=MessageResponse)
async def delete_criterion_set(
    criterion_set_id: int,
    service: CriterionSetService = Depends(get_criterion_set_service),
):
    """Delete criterion set (soft delete).
    
    Args:
        criterion_set_id: Criterion set ID.
        service: CriterionSet service dependency.
        
    Returns:
        Success message.
        
    Raises:
        HTTPException: If criterion set not found.
    """
    # Verify criterion set exists
    criterion_set = await service.get_by_id(criterion_set_id)
    if not criterion_set:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Criterion set not found",
        )
    
    success = await service.delete(criterion_set_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete criterion set",
        )
    
    return MessageResponse(message="Criterion set deleted successfully", success=True)


@router.get("/organization/{organization_id}/default", response_model=CriterionSetResponse)
async def get_default_criterion_set(
    organization_id: int,
    service: CriterionSetService = Depends(get_criterion_set_service),
):
    """Get default criterion set for an organization.
    
    Args:
        organization_id: Organization ID.
        service: CriterionSet service dependency.
        
    Returns:
        Default criterion set.
        
    Raises:
        HTTPException: If default set not found.
    """
    criterion_set = await service.get_default_by_organization_id(organization_id)
    if not criterion_set:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Default criterion set not found",
        )
    return criterion_set


@router.post("/import-excel", response_model=MessageResponse)
async def import_criterion_sets_from_excel(
    organization_id: int,
    file: UploadFile = File(...),
    criterion_service: CriterionService = Depends(get_criterion_service),
    criterion_set_service: CriterionSetService = Depends(get_criterion_set_service),
    evaluation_type_service: EvaluationTypeService = Depends(get_evaluation_type_service),
    organization_service: OrganizationService = Depends(get_organization_service),
):
    """Import criterion sets from Excel file.
    
    Args:
        organization_id: Organization ID.
        file: Excel file to import.
        criterion_service: Criterion service dependency.
        criterion_set_service: CriterionSet service dependency.
        evaluation_type_service: EvaluationType service dependency.
        organization_service: Organization service dependency.
        
    Returns:
        Success message.
        
    Raises:
        HTTPException: If organization not found or import fails.
    """
    import logging
    import tempfile
    from pathlib import Path
    
    import re
    from openpyxl import load_workbook  # type: ignore
    from app.infra.database.repository.criterion.dto import CreateCriterionDTO
    from app.infra.database.repository.criterion_set.dto import CreateCriterionSetDTO
    from app.infra.database.repository.evaluation_type.dto import CreateEvaluationTypeDTO
    
    logger = logging.getLogger(__name__)
    
    # Verify organization exists
    organization = await organization_service.get_by_id(organization_id)
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    
    # Check file type
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Only .xlsx and .xls files are supported",
        )
    
    tmp_path = None
    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_file:
            tmp_path = Path(tmp_file.name)
            content = await file.read()
            tmp_file.write(content)
        
        # Load Excel file
        wb = load_workbook(tmp_path, read_only=True, data_only=True)
        ws = wb.active
        
        rows_list = list(ws.iter_rows(values_only=True))
        
        # Skip header if present
        start_idx = 0
        if rows_list and len(rows_list[0]) >= 3:
            first_row = rows_list[0]
            first_col = str(first_row[0]).lower().strip() if first_row[0] else ""
            third_col = str(first_row[2]).lower().strip() if first_row[2] else ""
            
            header_keywords = ["название", "набор", "вопрос", "критерий", "тип", "name", "question", "type", "set"]
            valid_types = ["bool", "str", "num", "boolean", "string", "number"]
            
            is_header = any(kw in first_col for kw in header_keywords) or \
                       (third_col and third_col not in valid_types)
            
            if is_header:
                start_idx = 1
        
        # Parse data
        sets_data = {}
        for row_data in rows_list[start_idx:]:
            if len(row_data) < 3:
                continue
            
            set_name = str(row_data[0]).strip() if row_data[0] else ""
            criterion_question = str(row_data[1]).strip() if row_data[1] else ""
            criterion_type = str(row_data[2]).strip().lower() if row_data[2] else "bool"
            
            if not set_name or not criterion_question:
                continue
            
            # Normalize type
            type_mapping = {
                "boolean": "bool", "bool": "bool",
                "string": "str", "str": "str",
                "number": "num", "num": "num"
            }
            criterion_type = type_mapping.get(criterion_type, "bool")
            
            if set_name not in sets_data:
                sets_data[set_name] = []
            
            sets_data[set_name].append({
                "question": criterion_question,
                "type": criterion_type,
            })
        
        wb.close()
        
        if not sets_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No data found in Excel file",
            )
        
        # Get evaluation types
        evaluation_types = await evaluation_type_service.get_all()
        evaluation_types_by_name = {et.name: et for et in evaluation_types}
        evaluation_types_by_code = {et.code: et for et in evaluation_types}
        
        # Create criteria and sets
        created_sets = []
        created_criteria_count = 0
        
        for set_name, criteria_list in sets_data.items():
            # Check/create evaluation type
            evaluation_type_name = set_name
            evaluation_type_code = re.sub(r'[^a-zа-яё0-9_]', '', evaluation_type_name.lower().replace(' ', '_'))
            evaluation_type_code = re.sub(r'_+', '_', evaluation_type_code).strip('_')
            
            if not evaluation_type_code:
                evaluation_type_code = f"evaluation_type_{len(evaluation_types_by_code) + 1}"
            
            if evaluation_type_name in evaluation_types_by_name:
                evaluation_type_id = evaluation_types_by_name[evaluation_type_name].id
            else:
                # Check if code exists
                if evaluation_type_code in evaluation_types_by_code:
                    counter = 1
                    original_code = evaluation_type_code
                    while evaluation_type_code in evaluation_types_by_code:
                        evaluation_type_code = f"{original_code}_{counter}"
                        counter += 1
                
                # Create new evaluation type
                create_evaluation_type_dto = CreateEvaluationTypeDTO(
                    name=evaluation_type_name,
                    code=evaluation_type_code,
                    description=f"Автоматически создан при импорте набора критериев '{set_name}' из Excel",
                )
                
                evaluation_type = await evaluation_type_service.create(create_evaluation_type_dto)
                evaluation_type_id = evaluation_type.id
                
                evaluation_types_by_name[evaluation_type_name] = evaluation_type
                evaluation_types_by_code[evaluation_type_code] = evaluation_type
            
            criterion_ids = []
            
            # Create criteria
            for idx, criterion_data in enumerate(criteria_list):
                type_to_db_mapping = {
                    "bool": "boolean",
                    "str": "string",
                    "num": "number",
                    "boolean": "boolean",
                    "string": "string",
                    "number": "number",
                }
                db_value_type = type_to_db_mapping.get(criterion_data["type"], "boolean")
                
                base_code = f"{set_name.lower().replace(' ', '_')}_{idx + 1}"
                code = f"{base_code}_{criterion_data['type']}"
                
                create_criterion_dto = CreateCriterionDTO(
                    organization_id=organization_id,
                    evaluation_type_id=evaluation_type_id,
                    name=criterion_data["question"],
                    code=code,
                    value_type=db_value_type,
                    description=None,
                    sort_order=idx,
                )
                
                criterion = await criterion_service.create(create_criterion_dto)
                criterion_ids.append(criterion.id)
                created_criteria_count += 1
            
            if not criterion_ids:
                continue
            
            # Create criterion set
            create_set_dto = CreateCriterionSetDTO(
                organization_id=organization_id,
                name=set_name,
                description="Импортирован из Excel файла",
                is_default=False,
                criterion_ids=criterion_ids,
            )
            
            criterion_set = await criterion_set_service.create(create_set_dto)
            created_sets.append(criterion_set.name)
        
        result_message = (
            f"Successfully imported: {len(created_sets)} criterion sets, "
            f"{created_criteria_count} criteria"
        )
        
        return MessageResponse(message=result_message, success=True)
        
    except Exception as e:
        logger.error(f"Error importing Excel file: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to import Excel file: {str(e)}",
        )
    finally:
        # Cleanup
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
