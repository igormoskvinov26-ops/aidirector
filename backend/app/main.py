"""Rubl Пульт — FastAPI application entrypoint.

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
from app.api.routes.finance_analysis import router as finance_analysis_router
from app.api.routes.monthly_report import router as monthly_report_router
from app.api.routes.settings import router as settings_router
from app.api.yclients import YclientsНеНастроен
from app.config import settings
from app.database import check_db, init_db
from app.main_roles import ROLE_MASTER, ROLE_OPERATOR, ROLE_OWNER
from app.services import branches, configuration, credentials, salon

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
PUBLIC_PATHS = {"/health"}

# Пока владелец не заведён, пароля для входа не существует — спрашивать его
# не у кого. Открыт только мастер первичной настройки, и тот просит код,
# напечатанный в окне установки. Всё остальное отвечает «требуется
# настройка», а не пускает без пароля.
SETUP_PREFIX = "/api/setup"

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
OPERATOR_API_PREFIXES = ("/api/client-base", "/api/shift", "/api/me", "/api/salon", SYNC_STATE_PREFIX)

# Мастер заходит только за своими деньгами. Внутри /api/barbers ответ ещё и
# урезается до его собственной строки — одного лишь доступа к пути мало.
MASTER_API_PREFIXES = ("/api/barbers", "/api/me", "/api/salon", SYNC_STATE_PREFIX)


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


def настройка_не_закончена() -> bool:
    """Владельца нет нигде — ни в .env, ни среди заведённых через мастер."""
    return not (settings.owner_login and settings.owner_password) and not credentials.заведён(
        ROLE_OWNER
    )


def _resolve_identity(login: str, password: str) -> tuple[str, int | None, bool] | None:
    """Роль и привязка к мастеру по паре логин-пароль, либо None.

    Сравнения выполняются для всех учётных записей до проверки результата:
    иначе по времени ответа можно определить, существует ли такой логин.

    Источников два: .env, как было всегда, и учётные записи, заведённые через
    мастер первичной настройки. Первые проверяются первыми — у развёрнутых
    установок они уже работают, и перестать их принимать нельзя.
    """
    matched: tuple[str, int | None, bool] | None = None

    owner_login_ok = _same(login, settings.owner_login) and bool(settings.owner_login)
    owner_password_ok = _same(password, settings.owner_password) and bool(
        settings.owner_password
    )
    operator_login_ok = _same(login, settings.operator_login) and bool(
        settings.operator_login
    )
    operator_password_ok = _same(password, settings.operator_password) and bool(
        settings.operator_password
    )

    # Обе роли проверяются всегда, независимо от того, сработал ли .env:
    # ранний выход дал бы разницу во времени ответа между существующим и
    # несуществующим логином.
    owner_saved_ok = credentials.проверить_пароль(ROLE_OWNER, login, password)
    top_ok = credentials.проверить_пароль("top", login, password)
    operator_saved_ok = credentials.проверить_пароль(ROLE_OPERATOR, login, password)

    # Не главный филиал: свои управляющий и администратор. Главный владелец
    # (.env или мастер) входит всегда и один может управлять филиалами.
    ветка_управляющий = credentials.проверить_пароль(ROLE_OWNER, login, password, ветка=True)
    ветка_админ = credentials.проверить_пароль(ROLE_OPERATOR, login, password, ветка=True)
    главный_филиал = branches.главный()

    if top_ok:
        matched = (ROLE_OWNER, None, True)
    elif (owner_login_ok and owner_password_ok) or owner_saved_ok:
        # Владелец заведён отдельно — главный вход теперь Управляющий.
        matched = (ROLE_OWNER, None, not credentials.заведён("top"))
    elif ветка_управляющий:
        matched = (ROLE_OWNER, None, False)
    elif главный_филиал and ((operator_login_ok and operator_password_ok) or operator_saved_ok):
        matched = (ROLE_OPERATOR, None, False)
    elif ветка_админ:
        matched = (ROLE_OPERATOR, None, False)

    for account in settings.master_accounts:
        login_ok = _same(login, str(account.get("login", "")))
        password_ok = _same(password, str(account.get("password", "")))
        if login_ok and password_ok and matched is None:
            matched = (ROLE_MASTER, int(account["staff_id"]), False)

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

        path = request.url.path

        # Режим первичной настройки: пароля ещё не существует.
        if настройка_не_закончена():
            if path.startswith(SETUP_PREFIX):
                return await call_next(request)
            if not path.startswith("/api/"):
                # Статику отдаём: без неё мастер настройки не на чем открыть.
                return await call_next(request)
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Пульт ещё не настроен",
                    "setup_required": True,
                },
            )

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

        role, staff_id, top = identity
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
        request.state.top = top
        return await call_next(request)

    @staticmethod
    def _challenge() -> Response:
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Rubl Director"'},
            content="Authentication required",
        )


def _объявить_код_настройки() -> None:
    """Напечатать код первичной настройки и положить его в файл.

    Код нужен один раз — чтобы мастер настройки, открытый без пароля, не мог
    заполнить кто-то посторонний. Печатается в журнал, который видно в окне
    установки, и кладётся рядом с журналами: человек, который ставит
    программу, найдёт его в обоих местах, а посторонний — ни в одном.
    """
    код = credentials.выдать_код_настройки()
    рамка = "═" * 52
    logger.info(
        f"\n{рамка}\n  Пульт ещё не настроен.\n"
        f"  Откройте http://localhost:{settings.app_port} и введите код:\n\n"
        f"        {код}\n\n{рамка}"
    )
    # Пишем в output, а не рядом с журналами: в Docker именно эта папка
    # вынесена наружу, и только оттуда файл виден на самом компьютере.
    # Внутри контейнера он никому не нужен.
    try:
        папка = settings.output_dir
        папка.mkdir(parents=True, exist_ok=True)
        (папка / "код-настройки.txt").write_text(
            f"Код первичной настройки Пульта: {код}\n\n"
            "Он нужен один раз, при первом открытии. После того как заведена\n"
            "учётная запись владельца, код перестаёт действовать.\n",
            encoding="utf-8",
        )
        # Голый код латиницей — его читает установщик, чтобы показать человеку
        # окном. Кириллица и разметка там только помешают.
        (папка / "setup-code.txt").write_text(код, encoding="ascii")
    except OSError as сбой:
        logger.warning(f"код настройки не записан в файл: {сбой}")


def убрать_код_настройки() -> None:
    """Код отслужил: владелец заведён, и файл с кодом больше не нужен.

    Оставлять его — значит оставить на диске пропуск, которым уже нельзя
    воспользоваться, но который выглядит действующим.
    """
    for имя in ("код-настройки.txt", "setup-code.txt"):
        try:
            (settings.output_dir / имя).unlink(missing_ok=True)
        except OSError as сбой:
            logger.warning(f"файл {имя} не удалён: {сбой}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Rubl Пульт...")

    # Fail loudly. The old version swallowed this and served a half-dead app
    # where client-base, finance and AI silently returned 500 forever.
    await init_db()
    logger.info("Database ready")

    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.stories_dir.mkdir(parents=True, exist_ok=True)

    # Настройки интеграций и учётные записи читаются один раз при старте:
    # дальше за ними ходят из мест, где сессии базы под рукой нет, — из
    # middleware на каждый запрос и из выгрузки в фоне.
    from app.database import async_session

    # При обновлении приложение стартует раньше, чем установка накатит
    # миграцию: скрипты сначала поднимают контейнер, потом выполняют
    # alembic upgrade внутри него. В этот промежуток таблиц app_settings ещё
    # нет. Падать из-за этого нельзя — контейнер ушёл бы в перезапуск по
    # кругу, и миграция не смогла бы в него попасть. Поэтому здесь отказ —
    # не ошибка: работаем на значениях из .env, а управляемые подхватятся
    # при следующем запуске или первом сохранении.
    try:
        async with async_session() as session:
            await configuration.загрузить(session)
            await credentials.загрузить(session)
            await credentials.посеять_top_из_файла(session, "/app/top-seed.env")
            await salon.загрузить(session)
    except Exception as сбой:  # noqa: BLE001
        logger.warning(
            f"управляемые настройки не прочитаны (вероятно, миграция ещё не "
            f"применена): {type(сбой).__name__}. Работаю на значениях из .env"
        )

    await branches.восстановить_активный()

    if настройка_не_закончена():
        _объявить_код_настройки()
    else:
        обзор = configuration.обзор()
        if обзор["missing"]:
            logger.warning(
                "не настроены ключи: "
                + ", ".join(обзор["missing"])
                + " — раздел «Настройки → Интеграции»"
            )

    from app.services.sync import run_sync_loop

    from app.services.hub import run_hub_loop
    from app.services.settings_file import run_settings_file_loop

    sync_task = asyncio.create_task(run_sync_loop())
    hub_task = asyncio.create_task(run_hub_loop())
    file_task = asyncio.create_task(run_settings_file_loop())
    try:
        yield
    finally:
        for task in (sync_task, hub_task, file_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        logger.info("Shutting down...")


app = FastAPI(
    title="Rubl Пульт",
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
    finance_analysis_router,
    finance_router,
    monthly_report_router,
    operations_router,
    settings_router,
    shift_router,
    stories_router,
    sync_router,
):
    app.include_router(r)


@app.exception_handler(YclientsНеНастроен)
async def yclients_not_configured(
    request: Request, exc: YclientsНеНастроен
) -> JSONResponse:
    """Ненастроенная интеграция — это 503 с понятным текстом, а не 500.

    Раздел, которому нужны свежие данные из YCLIENTS, должен сказать «нет
    ключей», а не показать «внутренняя ошибка сервера»: по второму человек
    идёт искать поломку там, где её нет.
    """
    logger.info(f"{request.url.path}: YCLIENTS не настроен")
    return JSONResponse(
        status_code=503,
        content={"detail": str(exc), "needs_configuration": "yclients"},
    )


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
        "top": bool(getattr(request.state, "top", False)),
    }


@app.get("/api/info")
async def info() -> dict:
    обзор = configuration.обзор()
    return {
        "company_id": configuration.число("YCLIENTS_COMPANY_ID"),
        "sync_interval_minutes": settings.sync_interval_minutes,
        "sync_window_days": settings.sync_window_days,
        "version": "2.0.0",
        # Чего не хватает — по этому интерфейс показывает полосу «требуется
        # настройка» на любой странице, а не только в разделе настроек.
        "ready": обзор["ready"],
        "missing": обзор["missing"],
    }


if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    logger.info(f"Serving static files from {STATIC_DIR}")
else:
    logger.info("No static directory, API-only mode")
