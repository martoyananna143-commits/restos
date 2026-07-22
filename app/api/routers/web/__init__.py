"""Web data API — aggregated router for the standalone web app."""

from fastapi import APIRouter

from . import ai_data, criterion_sets_data, employees_data, evaluations_data

router = APIRouter(prefix="/web", tags=["web-data"])
router.include_router(employees_data.router)
router.include_router(ai_data.router)
router.include_router(criterion_sets_data.router)
router.include_router(evaluations_data.router)
