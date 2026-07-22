from dependency_injector import containers, providers

from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import DefaultKeyBuilder, RedisStorage

from app.infra.database.connection.postgresql.resource import Postgresql
from app.infra.database.repository.criterion.criterion_asyncpg import (
    CriterionRepositoryAsyncpg,
)
from app.infra.database.repository.criterion_set.criterion_set_asyncpg import (
    CriterionSetRepositoryAsyncpg,
)
from app.infra.database.repository.criterion_value.criterion_value_asyncpg import (
    CriterionValueRepositoryAsyncpg,
)
from app.infra.database.repository.employee.employee_asyncpg import (
    EmployeeRepositoryAsyncpg,
)
from app.infra.database.repository.evaluation.evaluation_asyncpg import (
    EvaluationRepositoryAsyncpg,
)
from app.infra.database.repository.evaluation_type.evaluation_type_asyncpg import (
    EvaluationTypeRepositoryAsyncpg,
)
from app.infra.database.repository.organization.organization_asyncpg import (
    OrganizationRepositoryAsyncpg,
)
from app.infra.database.repository.user.user_asyncpg import UserRepositoryAsyncpg
from app.internal.services.ai_assistant_service import AIAssistantService
from app.internal.services.analytics_service import AnalyticsService
from app.internal.services.criterion_service import CriterionService
from app.internal.services.criterion_set_service import CriterionSetService
from app.internal.services.employee_service import EmployeeService
from app.internal.services.evaluation_service import EvaluationService
from app.internal.services.evaluation_type_service import EvaluationTypeService
from app.internal.services.excel_report_service import ExcelReportService
from app.internal.services.export_data_service import ExportDataService
from app.internal.services.google_criterion_sync_service import GoogleCriterionSyncService
from app.internal.services.google_drive_service import GoogleDriveService
from app.internal.services.google_sheet_service import GoogleSheetService
from app.internal.services.invitation_service import InvitationService
from app.internal.services.organization_service import OrganizationService
from app.internal.services.pdf_report_service import PDFReportService
from app.internal.services.user_service import UserService
from app.settings import config


# Helper function to create init function for Resource provider
def _make_init_pool(pg_provider):
    async def _init():
        pg_instance = pg_provider()
        return await pg_instance.init(
            dsn=config.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://"),
            min_size=5,
            max_size=config.DATABASE_POOL_SIZE,
            max_queries=50000,
            max_inactive_connection_lifetime=300.0,
            command_timeout=60.0,
        )
    return _init


class Container(containers.DeclarativeContainer):
    """Application dependency injection container."""

    postgresql = providers.Singleton(Postgresql)

    postgresql_resource: providers.Resource = providers.Resource(
        _make_init_pool(postgresql),
    )

    # Repository providers
    # Pass resource provider directly - it will be resolved automatically
    user_repository = providers.Factory(
        UserRepositoryAsyncpg,
        pool=postgresql_resource,
    )

    # Organization repository and service
    organization_repository = providers.Factory(
        OrganizationRepositoryAsyncpg,
        pool=postgresql_resource,
    )

    organization_service = providers.Factory(
        OrganizationService,
        repository=organization_repository,
    )

    # Employee repository and service
    employee_repository = providers.Factory(
        EmployeeRepositoryAsyncpg,
        pool=postgresql_resource,
    )

    employee_service = providers.Factory(
        EmployeeService,
        repository=employee_repository,
    )

    # EvaluationType repository and service
    evaluation_type_repository = providers.Factory(
        EvaluationTypeRepositoryAsyncpg,
        pool=postgresql_resource,
    )

    evaluation_type_service = providers.Factory(
        EvaluationTypeService,
        repository=evaluation_type_repository,
    )

    # Criterion repository and service
    criterion_repository = providers.Factory(
        CriterionRepositoryAsyncpg,
        pool=postgresql_resource,
    )

    criterion_service = providers.Factory(
        CriterionService,
        repository=criterion_repository,
    )

    # CriterionSet repository and service
    criterion_set_repository = providers.Factory(
        CriterionSetRepositoryAsyncpg,
        pool=postgresql_resource,
    )

    criterion_set_service = providers.Factory(
        CriterionSetService,
        repository=criterion_set_repository,
    )

    # Evaluation repository and service
    evaluation_repository = providers.Factory(
        EvaluationRepositoryAsyncpg,
        pool=postgresql_resource,
    )

    evaluation_service = providers.Factory(
        EvaluationService,
        repository=evaluation_repository,
    )

    # CriterionValue repository
    criterion_value_repository = providers.Factory(
        CriterionValueRepositoryAsyncpg,
        pool=postgresql_resource,
    )

    # PDF Report service
    pdf_report_service = providers.Factory(
        PDFReportService,
    )

    # Excel Report service
    excel_report_service = providers.Factory(
        ExcelReportService,
    )

    # Analytics service
    analytics_service = providers.Factory(
        AnalyticsService,
        evaluation_repository=evaluation_repository,
    )

    # Export data service
    export_data_service = providers.Factory(
        ExportDataService,
        criterion_value_repository=criterion_value_repository,
    )

    # Storage provider (Redis or Memory)
    storage = providers.Singleton(
        lambda: RedisStorage.from_url(
            config.REDIS_DSN,
            key_builder=DefaultKeyBuilder(with_bot_id=True, with_destiny=True),
        )
        if config.TGBOT_USE_REDIS
        else MemoryStorage()
    )

    # AI Assistant service
    ai_assistant_service = providers.Factory(
        AIAssistantService,
        storage=storage,
    )

    # Invitation service
    invitation_service = providers.Factory(
        InvitationService,
        storage=storage,
    )

    google_sheet_service = providers.Factory(GoogleSheetService)
    google_drive_service = providers.Factory(GoogleDriveService)
    google_criterion_sync_service = providers.Factory(
        GoogleCriterionSyncService,
        sheet_service=google_sheet_service,
        criterion_set_service=criterion_set_service,
        criterion_service=criterion_service,
    )

    # Service providers
    user_service = providers.Factory(
        UserService,
        repository=user_repository,
    )
