"""Application startup setup — creates default admin if not exists.

Runs automatically on every startup (idempotent).

Controlled by env vars:
  DEFAULT_ADMIN_LOGIN     (default: "admin")
  DEFAULT_ADMIN_PASSWORD  (default: "admin123")  ← change in .env!
  DEFAULT_ADMIN_NAME      (default: "Главный администратор")
  DEFAULT_ORG_NAME        (default: "Моя организация")
  DEFAULT_ORG_CODE        (default: "main")
"""

import logging

import bcrypt

from app.infra.database.repository.employee.dto import CreateEmployeeDTO
from app.infra.database.repository.employee.employee_asyncpg import EmployeeRepositoryAsyncpg
from app.infra.database.repository.evaluation_type.dto import CreateEvaluationTypeDTO
from app.infra.database.repository.evaluation_type.evaluation_type_asyncpg import EvaluationTypeRepositoryAsyncpg
from app.infra.database.repository.organization.dto import CreateOrganizationDTO
from app.infra.database.repository.organization.dto import UpdateOrganizationDTO
from app.infra.database.repository.organization.organization_asyncpg import OrganizationRepositoryAsyncpg
from app.infra.database.repository.organization.organization_asyncpg import normalize_organization_meta
from app.internal.services.employee_service import EmployeeService
from app.internal.services.evaluation_type_service import EvaluationTypeService
from app.internal.services.organization_service import OrganizationService
from app.internal import Container

logger = logging.getLogger(__name__)

# bcrypt limit: 72 bytes; truncate to avoid error
def _hash_password(password: str) -> str:
    pwd_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode()


async def ensure_default_admin(container: Container) -> None:
    """Create default organization + admin employee on first startup.

    Builds services directly from the DB pool (same pattern as local_bot.py)
    instead of going through the DI factory chain, which avoids coroutine
    resolution issues with async Resource providers.
    """
    from app.settings import config

    login    = config.DEFAULT_ADMIN_LOGIN
    password = config.DEFAULT_ADMIN_PASSWORD
    org_name = config.DEFAULT_ORG_NAME
    org_code = config.DEFAULT_ORG_CODE
    admin_name = config.DEFAULT_ADMIN_NAME

    # ── Resolve the pool the same way local_bot.py does it ──────────────────
    # postgresql_resource is an async providers.Resource; awaiting it gives
    # the initialized BuildPgPool (initializes on first call, cached after).
    pool = await container.postgresql_resource()

    employee_service     = EmployeeService(repository=EmployeeRepositoryAsyncpg(pool=pool))
    org_service          = OrganizationService(repository=OrganizationRepositoryAsyncpg(pool=pool))
    eval_type_service    = EvaluationTypeService(repository=EvaluationTypeRepositoryAsyncpg(pool=pool))

    # ── 1. Resolve existing partial bootstrap state ──────────────────────────
    existing = await employee_service.get_by_web_login(login)
    all_orgs = await org_service.get_all()
    org = next((o for o in all_orgs if o.code == org_code), None)

    if not org:
        if existing:
            raise RuntimeError("default bootstrap state is invalid")
        org = await org_service.create(CreateOrganizationDTO(name=org_name, code=org_code))
        logger.info("Created organization '%s' (id=%s)", org.name, org.id)
    else:
        logger.info("Using existing organization '%s' (id=%s)", org.name, org.id)

    admin = existing
    if admin is None:
        emp_types = await employee_service.get_employee_types()
        if not emp_types:
            raise RuntimeError("default bootstrap employee type is unavailable")
        admin_type = next(
            (t for t in emp_types if t.get("is_administrator") or t.get("code") in ("admin", "administrator")),
            emp_types[0],
        )
        hashed = _hash_password(password)
        admin = await employee_service.create(
            CreateEmployeeDTO(
                organization_id=org.id,
                employee_type_id=admin_type["id"],
                full_name=admin_name,
                meta={"web_login": login, "hashed_password": hashed},
            )
        )

    org_meta = normalize_organization_meta(getattr(org, "meta", None))
    if not org_meta.get("created_by_employee_id"):
        org_meta["created_by_employee_id"] = admin.id
        org_meta["created_by_telegram_id"] = admin.telegram_id
        await org_service.update(org.id, UpdateOrganizationDTO(meta=org_meta))

    # ── 2. Ensure the default evaluation type exists ─────────────────────────
    existing_types = await eval_type_service.get_all(organization_id=org.id)
    if not existing_types:
        await eval_type_service.create(CreateEvaluationTypeDTO(
            organization_id=org.id,
            name="Стандартная оценка",
            code="standard",
            description="Стандартный тип оценки сотрудников",
        ))
        logger.info("Created default evaluation type 'Стандартная оценка' for org %s", org.id)
