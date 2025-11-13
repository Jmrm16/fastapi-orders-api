from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine, Base
from app.api.v1 import api_router
from app.core.exceptions import CommerceException


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create DB tables automatically on startup if using SQLite/local dev
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configure CORS
if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# Global domain exception handler
@app.exception_handler(CommerceException)
async def commerce_exception_handler(request: Request, exc: CommerceException):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": exc.__class__.__name__, "message": exc.message},
    )


@app.get("/health", tags=["Health"])
def health_check():
    """Simple liveness probe for Docker and Kubernetes."""
    return {"status": "healthy", "service": settings.PROJECT_NAME}


@app.get("/", tags=["Root"])
def root_info():
    """Root endpoint welcoming API consumers and linking to documentation."""
    return {
        "message": f"Welcome to {settings.PROJECT_NAME}",
        "docs_url": "/docs",
        "health_check": "/health",
        "api_v1": settings.API_V1_STR,
    }


# Mount API v1
app.include_router(api_router, prefix=settings.API_V1_STR)
