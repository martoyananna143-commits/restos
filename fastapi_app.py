"""FastAPI application entry point for running with uvicorn."""

from app.api.main import app

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "fastapi_app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
