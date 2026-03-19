"""FastAPI application main module."""

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import webapp
from app.api.routers import web_auth, web_data
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
        ])
        owns_container = True
    
    app.state.container = container

    # Create default admin on first startup (idempotent)
    try:
        await ensure_default_admin(container)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "Could not run default admin setup: %s", exc
        )

    yield

    # Only shutdown if we own the container
    if owns_container:
        await container.shutdown_resources()


def create_app() -> FastAPI:
    """Create and configure FastAPI application.
    
    Returns:
        Configured FastAPI application instance.
    """
    from app.settings import config
    
    app = FastAPI(
        title="Yarbot API",
        description="API for Employee Evaluation System (Web Forms Only)",
        version="1.0.0",
        lifespan=lifespan,
    )
    
    # Configure CORS
    # In production, set CORS_ORIGINS environment variable to specific domains
    # Example: CORS_ORIGINS="https://yourdomain.com,https://webapp.yourdomain.com"
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_credentials=config.CORS_ALLOW_CREDENTIALS,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Telegram-Id", "X-Telegram-Chat-Id", "X-Organization-Id"],
    )
    
    app.include_router(webapp.router, prefix="/api")      # /api/webapp/...
    app.include_router(web_auth.router, prefix="/api")    # /api/web/auth/...
    app.include_router(web_data.router, prefix="/api")    # /api/web/...
    
    @app.get("/health")
    async def health_check():
        """Health check endpoint.
        
        Returns:
            Health status.
        """
        return {"status": "healthy"}
    
    @app.get("/")
    async def root():
        """Root endpoint.
        
        Returns:
            Welcome message.
        """
        return {
            "message": "Yarbot API - Web Forms",
            "version": "1.0.0",
            "docs": "/docs",
            "redoc": "/redoc",
        }
    
    return app


# Create application instance
app = create_app()
