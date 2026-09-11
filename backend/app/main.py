"""Rubl AI Director — FastAPI application entrypoint.

Wiring only. All business logic lives in app/services, all endpoints in
app/api/routes. The previous version carried 522 lines with seven inline
endpoints and four copies of the slot loop.
"""

import asyncio
import base64
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes.ai import router as ai_router
from app.api.routes.client_base import router as client_base_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.employees import router as employees_router
from app.api.routes.finance import router as finance_router
from app.api.routes.operations import router as operations_router
from app.api.routes.stories import router as stories_router
from app.api.routes.sync import router as sync_router
from app.config import settings
from app.database import check_db, init_db

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
PUBLIC_PATHS = {"/health"}


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """HTTP Basic auth for everything except /health.

    Credentials come from .env with no fallback default, and both fields are
    compared in constant time even when the login is wrong, so response timing
    does not leak whether a username exists.
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Basic "):
            return self._challenge()

        try:
            login, password = base64.b64decode(auth[6:]).decode().split(":", 1)
        except Exception:
            return self._challenge()

        login_ok = secrets.compare_digest(login, settings.admin_login)
        password_ok = secrets.compare_digest(password, settings.admin_password)
        if not (login_ok and password_ok):
            logger.warning(f"failed auth from {request.client.host if request.client else '?'}")
            return self._challenge()

        return await call_next(request)

    @staticmethod
    def _challenge() -> Response:
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Rubl Director"'},
            content="Authentication required",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Rubl AI Director...")

    # Fail loudly. The old version swallowed this and served a half-dead app
    # where client-base, finance and AI silently returned 500 forever.
    await init_db()
    logger.info("Database ready")

    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.stories_dir.mkdir(parents=True, exist_ok=True)

    from app.services.sync import run_sync_loop

    sync_task = asyncio.create_task(run_sync_loop())
    try:
        yield
    finally:
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            pass
        logger.info("Shutting down...")


app = FastAPI(
    title="Rubl AI Director",
    version="2.0.0",
    description="AI-powered management system for Rubl Barbershop",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.debug else None,
    redoc_url=None,
)

# Order matters: CORS is added last so it runs first and can answer preflight
# requests before auth rejects them.
app.add_middleware(BasicAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

for r in (
    ai_router,
    client_base_router,
    dashboard_router,
    employees_router,
    finance_router,
    operations_router,
    stories_router,
    sync_router,
):
    app.include_router(r)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """Turn guard-rail violations (bad or over-wide date ranges) into 400, not 500."""
    logger.warning(f"bad request {request.url.path}: {exc}")
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "2.0.0", "database": await check_db()}


@app.get("/api/info")
async def info() -> dict:
    return {
        "company_id": settings.yclients_company_id,
        "sync_interval_minutes": settings.sync_interval_minutes,
        "sync_window_days": settings.sync_window_days,
        "version": "2.0.0",
    }


if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    logger.info(f"Serving static files from {STATIC_DIR}")
else:
    logger.info("No static directory, API-only mode")
