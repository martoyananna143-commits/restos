"""FastAPI application main module."""

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx

from app.api.routers import webapp
from app.api.routers import web_auth, web_data
from app.api.routers import account_invitation_auth
from app.api.routers import account_standalone_auth
from app.api.routers import account_sessions
from app.api.routers import account_web_sessions
from app.api.routers import account_passkeys
from app.api.routers import assessment_templates
from app.api.routers import account_assessments
from app.api.routers import account_assessment_management
from app.api.setup import ensure_default_admin
from app.internal import Container

# Shared container (set externally when running with bot)
_shared_container: Optional[Container] = None
# Shared bot instance (set externally when running with bot)
_shared_bot = None


def set_shared_container(container: Container):
    """Set shared container for use with bot."""
    global _shared_container
    _shared_container = container


def set_shared_bot(bot):
    """Set shared bot instance for use in API."""
    global _shared_bot
    _shared_bot = bot


def get_shared_bot():
    """Get shared bot instance."""
    return _shared_bot


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI application.
    
    Handles startup and shutdown events.
    Uses shared container if available (when running with bot).
    
    Args:
        app: FastAPI application instance.
    """
    global _shared_container
    
    # Use shared container or create new one
    if _shared_container is not None:
        container = _shared_container
        owns_container = False
    else:
        container = Container()
        container.wire(modules=[
            __name__,
            "app.api.deps",
            "app.api.routers.webapp",
            "app.api.routers.web_auth",
            "app.api.routers.web_data",
            "app.api.routers.web",
        ])
        owns_container = True
    
    app.state.container = container
    app.state.sms_http_client = httpx.AsyncClient()

    # Pilot Account onboarding is explicit. The legacy organization/employee
    # bootstrap remains opt-in for development and existing installations only.
    from app.settings import config

    if config.LEGACY_DEFAULT_ADMIN_BOOTSTRAP_ENABLED:
        try:
            await ensure_default_admin(container)
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning(
                "Could not run default admin setup: %s", exc
            )

    yield

    await app.state.sms_http_client.aclose()

    # Only shutdown if we own the container
    if owns_container:
        await container.shutdown_resources()


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    import logging as _logging
    from app.settings import config

    # Fail fast in production if critical secrets are misconfigured.
    config.validate_production_security()

    is_production = config.APP_ENV == "production"
    _log = _logging.getLogger(__name__)

    if is_production and config.CORS_ORIGINS == ["*"]:
        _log.warning(
            "SECURITY: CORS_ORIGINS is set to '*' in production — "
            "restrict to specific origins via the CORS_ORIGINS env variable"
        )

    app = FastAPI(
        title="Restos API",
        description="API системы оценки сотрудников Restos",
        version="1.0.0",
        lifespan=lifespan,
        # Disable interactive docs in production to avoid exposing the API schema.
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_credentials=config.CORS_ALLOW_CREDENTIALS,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-RestOS-Web-Session", "X-Telegram-Id", "X-Telegram-Chat-Id", "X-Organization-Id"],
    )
    account_invitation_auth.configure_account_auth_http_security(app)

    app.include_router(webapp.router, prefix="/api")
    app.include_router(web_auth.router, prefix="/api")
    app.include_router(web_data.router, prefix="/api")
    app.include_router(account_invitation_auth.router)
    app.include_router(account_standalone_auth.router)
    app.include_router(account_sessions.router)
    app.include_router(account_web_sessions.router)
    app.include_router(account_passkeys.router)
    app.include_router(assessment_templates.router)
    app.include_router(account_assessments.router)
    app.include_router(account_assessment_management.router)

    @app.get("/health")
    async def health_check():
        return {"status": "healthy"}

    @app.get("/")
    async def root():
        info: dict = {"message": "Restos API", "version": "1.0.0"}
        if not is_production:
            info["docs"] = "/docs"
            info["redoc"] = "/redoc"
        return info

    return app


# Create application instance
app = create_app()
