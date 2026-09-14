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

ROLE_OWNER = "owner"
ROLE_OPERATOR = "operator"

# Что разрешено роли operator помимо статики страницы: только база обзвона.
# Список из префиксов, а не из точных путей, потому что под /api/client-base
# лежат и задачи, и результаты звонков, и они ещё будут добавляться.
OPERATOR_API_PREFIXES = ("/api/client-base", "/api/me")


def _resolve_role(login: str, password: str) -> str | None:
    """Вернуть роль по паре логин-пароль либо None.

    Все четыре сравнения выполняются всегда, до проверки результата: иначе по
    времени ответа можно определить, существует ли такой логин.
    """
    owner_login_ok = secrets.compare_digest(login, settings.owner_login)
    owner_password_ok = secrets.compare_digest(password, settings.owner_password)
    operator_login_ok = secrets.compare_digest(login, settings.operator_login)
    operator_password_ok = secrets.compare_digest(password, settings.operator_password)

    if owner_login_ok and owner_password_ok:
        return ROLE_OWNER
    if operator_login_ok and operator_password_ok:
        return ROLE_OPERATOR
    return None


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """HTTP Basic auth с двумя ролями, всё кроме /health закрыто.

    Логины и пароли берутся из .env без значений по умолчанию. Роль владельца
    видит всё; роль оператора — только базу обзвона, остальные api-маршруты
    получают 403. Разграничение живёт здесь, а не в отдельных проверках внутри
    маршрутов: новый маршрут по умолчанию закрыт для оператора, а не открыт.
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

        role = _resolve_role(login, password)
        if role is None:
            logger.warning(f"failed auth from {request.client.host if request.client else '?'}")
            return self._challenge()

        path = request.url.path
        if role == ROLE_OPERATOR and path.startswith("/api/"):
            if not path.startswith(OPERATOR_API_PREFIXES):
                logger.warning(f"operator denied {path}")
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Недостаточно прав для этого раздела"},
                )

        request.state.role = role
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


@app.get("/api/me")
async def me(request: Request) -> dict:
    """Роль текущего пользователя — по ней интерфейс решает, что показывать."""
    return {"role": getattr(request.state, "role", ROLE_OPERATOR)}


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
