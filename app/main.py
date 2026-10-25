from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.core.exceptions import AppException


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB schema & tables
    init_db()
    yield
    # Shutdown logic (if any)


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

# CORS Middleware Configuration (Supporting React Native mobile app, Expo web, and LAN IPs)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------------------------------------
# Global Exception Handlers
# -------------------------------------------------------------
@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
            },
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        field_loc = " -> ".join([str(loc_item) for loc_item in err.get("loc", [])])
        errors.append(
            {
                "field": field_loc,
                "message": err.get("msg"),
                "type": err.get("type"),
            }
        )
    status_code = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Input validation failed. Please check the supplied fields.",
                "details": errors,
            },
        },
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": {
                "code": "DATABASE_ERROR",
                "message": "A database integrity error occurred while executing the transaction.",
                "details": str(exc) if settings.DEBUG else None,
            },
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected server error occurred.",
                "details": str(exc) if settings.DEBUG else None,
            },
        },
    )


# -------------------------------------------------------------
# Include API Routers
# -------------------------------------------------------------
app.include_router(api_v1_router, prefix=settings.API_V1_STR)


@app.get("/", tags=["Health"])
def root():
    return {
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs_url": "/docs",
        "status": "operational",
    }


@app.get("/health", tags=["Health"])
@app.get(f"{settings.API_V1_STR}/health", tags=["Health"])
def health_check():
    # Verify DB connectivity
    db = SessionLocal()
    db_status = "healthy"
    try:
        from sqlalchemy import text

        db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
    finally:
        db.close()

    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "database": db_status,
        "environment": settings.ENVIRONMENT,
        "version": settings.VERSION,
    }
