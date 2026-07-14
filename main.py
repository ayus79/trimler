"""
uvicorn main:app --port 8090 --workers 1 --reload
"""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.middleware.rate_limiter.middleware import RateLimitFastAPIMiddleware
from app.middleware.docs_protection.docs_protection_middleware import (
    DocsProtectionMiddleware,
)
from app.utils.log_config import log_message
from app.config.settings import settings
from app.database.migrations import run_startup_migrations
from app.database.postgres_client import PostgresClient
from app.database.redis_client import RedisClient
from app.database.click_flush import run_click_flush_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_startup_migrations()
    flush_task = asyncio.create_task(run_click_flush_loop())
    yield
    flush_task.cancel()


app = FastAPI(
    title=f"{settings.app_name}", version=settings.app_version, lifespan=lifespan
)

# Docs Protection Middleware - password protect OpenAPI docs (MUST be before CORS)
# This ensures the WWW-Authenticate header is not modified by CORS
app.add_middleware(DocsProtectionMiddleware, enabled=True)

# CORS configs
allowed_origins = ["*"] if settings.app_env in ["local", "development"] else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate Limiting Middleware
app.add_middleware(RateLimitFastAPIMiddleware)

# Static assets (CSS/JS for the Jinja UI)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


# Routes Register
from app.modules.url_shortner.routes import (
    url_shortner_router,
    url_shortner_page_router,
)
from app.modules.url_redirect.routes import url_redirect_router

app.include_router(url_shortner_router)
app.include_router(url_shortner_page_router)


# Health check
@app.get("/health", tags=["Health"])
async def health_check():
    checks = {"database": "unknown", "redis": "unknown"}
    healthy = True

    try:
        db_client = PostgresClient()
        await db_client.fetch_value("SELECT 1")
        checks["database"] = "ok"
    except Exception as e:
        log_message(f"[Health Check] Database check failed: {e}", error=True)
        checks["database"] = "unavailable"
        healthy = False

    try:
        redis_client = RedisClient()
        await redis_client.async_client.ping()
        checks["redis"] = "ok"
    except Exception as e:
        log_message(f"[Health Check] Redis check failed: {e}", error=True)
        checks["redis"] = "unavailable"
        healthy = False

    return JSONResponse(
        content={"status": "ok" if healthy else "degraded", "checks": checks},
        status_code=200 if healthy else 503,
    )


# Handle 404 Not Found (for non-existent routes)
@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    """
    Handle 404 Not Found errors for non-existent routes.
    FastAPI uses status code 404 for missing routes.
    """
    return JSONResponse(
        status_code=404, content={"status": False, "message": "Page not found"}
    )


# Standardized HTTP Exception Handler
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Handle HTTPException and return standardized error format.
    Catches all raised HTTPException (404, 500, etc.)
    """
    # Log based on status code severity
    log_msg = (
        f"HTTPException ({exc.status_code}) | URL: {request.url} | Error: {exc.detail}"
    )

    if exc.status_code >= 500:
        # Server errors (500+) - Log as ERROR
        log_message(log_msg, error=True)
    elif exc.status_code == 404:
        # Not found - Log as WARNING
        log_message(log_msg, warning=True)
    elif exc.status_code >= 400:
        # Client errors (400-499) - Log as WARNING
        log_message(log_msg, warning=True)
    else:
        # Other status codes - Log as INFO
        log_message(log_msg, info=True)

    return JSONResponse(
        status_code=exc.status_code, content={"status": False, "message": exc.detail}
    )


# Validation Error Handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Handle FastAPI validation errors and return standardized format.
    Shows only the FIRST validation error to guide user step-by-step.
    """
    errors = exc.errors()

    # Get the first error
    if errors:
        first_error = errors[0]

        # Extract field name from location (e.g., ['query', 'status'] -> 'status')
        field_location = first_error.get("loc", [])
        field_name = field_location[-1] if field_location else "field"

        # Get error type and message
        error_type = first_error.get("type", "")
        error_msg = first_error.get("msg", "")

        # Create user-friendly message based on error type
        if "missing" in error_type:
            message = f"Required field '{field_name}' is missing"
        elif "invalid" in error_type or "type_error" in error_type:
            message = f"Invalid value for field '{field_name}': {error_msg}"
        elif "enum" in error_type:
            # For enum validation, show allowed values
            message = f"Invalid value for field '{field_name}'. {error_msg}"
        else:
            message = f"Validation error in field '{field_name}': {error_msg}"
    else:
        message = "Request validation error"

    # Log validation error as WARNING
    log_msg = f"ValidationError (422) | URL: {request.url} | Message: {message} | Total Errors: {len(errors)}"
    log_message(log_msg, warning=True)

    return JSONResponse(status_code=422, content={"status": False, "message": message})


# General Exception Handler
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """
    Handle all uncaught exceptions (fallback handler).
    This catches any exception that wasn't handled by specific handlers above.
    """
    # Log as CRITICAL since these are unexpected errors
    log_msg = f"UnhandledException (500) | URL: {request.url} | Error: {str(exc)} | Type: {type(exc).__name__}"
    log_message(log_msg, critical=True)

    # In production, don't expose internal error details
    return JSONResponse(
        status_code=500,
        content={
            "status": False,
            "message": "An unexpected error occurred. Please try again later.",
        },
    )


# Registered LAST: this router matches any single path segment as
# GET /{short_code}. Registering it before /health, /docs, /static, etc.
# would let it swallow those requests instead (Starlette matches routes
# in registration order, first match wins).
app.include_router(url_redirect_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0")
