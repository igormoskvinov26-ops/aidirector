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
from app.api.routes.barber_month import router as barber_month_router
from app.api.routes.bookings import router as bookings_router
from app.api.routes.client_base import router as client_base_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.employees import router as employees_router
from app.api.routes.finance import router as finance_router
from app.api.routes.operations import router as operations_router
from app.api.routes.shift import router as shift_router
from app.api.routes.stories import router as stories_router
from app.api.routes.sync import router as sync_router
from app.config import settings
from app.database import check_db, init_db
from app.main_roles import ROLE_MASTER, ROLE_OPERATOR, ROLE_OWNER

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
PUBLIC_PATHS = {"/health"}

# Что разрешено роли operator помимо статики страницы: только база обзвона.
# Расчёт зарплаты администратору не показываем — это дело управляющего.
# Решение владельца 18.09.2026. Список из префиксов, а не из точных путей,
# потому что под /api/client-base лежат и задачи, и результаты звонков, и
# они ещё будут добавляться.
# Состояние выгрузки открыто всем: надпись «данные обновлены тогда-то» стоит
# на каждой странице, и без неё администратор со стойки не отличит свежие
# цифры от вчерашних. Секретов в ответе нет — время, шаг и количества строк.
# Запуск выгрузки (/api/sync/trigger) остаётся только у владельца.
SYNC_STATE_PREFIX = "/api/sync/status"

# Смену открывает и закрывает администратор — значит, раздел смены ему открыт.
# Решение владельца 23.09.2026.
OPERATOR_API_PREFIXES = ("/api/client-base", "/api/shift", "/api/me", SYNC_STATE_PREFIX)

# Мастер заходит только за своими деньгами. Внутри /api/barbers ответ ещё и
# урезается до его собственной строки — одного лишь доступа к пути мало.
MASTER_API_PREFIXES = ("/api/barbers", "/api/me", SYNC_STATE_PREFIX)


def _same(введено: str, ожидается: str) -> bool:
    """Сравнение пары строк за одинаковое время, при любых символах.

    Сравниваются байты, а не строки. secrets.compare_digest со строками
    отказывается работать, если в любой из них есть хоть один символ вне
    латиницы: он поднимает TypeError. На живой установке это означало, что
    достаточно одной кириллической буквы в пароле — своём или просто
    набранном в русской раскладке, — и вход переставал работать вообще у
    всех, причём с ошибкой сервера вместо отказа в пароле.

    Байты сравниваются за то же постоянное время, так что защита от подбора
    по времени ответа остаётся.
    """
    return secrets.compare_digest(введено.encode("utf-8"), ожидается.encode("utf-8"))


def _resolve_identity(login: str, password: str) -> tuple[str, int | None] | None:
    """Роль и привязка к мастеру по паре логин-пароль, либо None.

    Сравнения выполняются для всех учётных записей до проверки результата:
    иначе по времени ответа можно определить, существует ли такой логин.
    """
    matched: tuple[str, int | None] | None = None

    owner_login_ok = _same(login, settings.owner_login)
    owner_password_ok = _same(password, settings.owner_password)
    operator_login_ok = _same(login, settings.operator_login)
    operator_password_ok = _same(password, settings.operator_password)

    if owner_login_ok and owner_password_ok:
        matched = (ROLE_OWNER, None)
    elif operator_login_ok and operator_password_ok:
        matched = (ROLE_OPERATOR, None)

    for account in settings.master_accounts:
        login_ok = _same(login, str(account.get("login", "")))
        password_ok = _same(password, str(account.get("password", "")))
        if login_ok and password_ok and matched is None:
            matched = (ROLE_MASTER, int(account["staff_id"]))

    return matched


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

        identity = _resolve_identity(login, password)
        if identity is None:
            logger.warning(f"failed auth from {request.client.host if request.client else '?'}")
            return self._challenge()

        role, staff_id = identity
        path = request.url.path
        allowed = {
            ROLE_OPERATOR: OPERATOR_API_PREFIXES,
            ROLE_MASTER: MASTER_API_PREFIXES,
        }.get(role)
        if allowed is not None and path.startswith("/api/") and not path.startswith(allowed):
            logger.warning(f"{role} denied {path}")
            return JSONResponse(
                status_code=403,
                content={"detail": "Недостаточно прав для этого раздела"},
            )

        request.state.role = role
        request.state.staff_id = staff_id
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
    barber_month_router,
    bookings_router,
    client_base_router,
    dashboard_router,
    employees_router,
    finance_router,
    operations_router,
    shift_router,
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
    """Кто вошёл — по этому интерфейс решает, что показывать."""
    staff_id = getattr(request.state, "staff_id", None)
    name = next(
        (
            r["name"]
            for r in settings.barber_payroll_rules
            if int(r["staff_id"]) == staff_id
        ),
        None,
    )
    return {
        "role": getattr(request.state, "role", ROLE_MASTER),
        "staff_id": staff_id,
        "name": name,
    }


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
