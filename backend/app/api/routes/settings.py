"""«Настройки → Интеграции» и мастер первичной настройки.

Два набора маршрутов с разной защитой:

  /api/settings/*  — только владелец. Проверка здесь, на сервере: спрятать
                     кнопку в интерфейсе — это удобство, а не защита.
  /api/setup/*     — открыты, пока владелец не заведён вообще: пароля, которым
                     их закрыть, в этот момент не существует. Вместо пароля
                     спрашивается код, напечатанный в окне установки. Как
                     только владелец заведён, эти маршруты отвечают отказом.

Ни один маршрут не возвращает сохранённый секрет целиком — ни в ответе, ни
в поле формы, ни в журнале. Наружу уходят только «заполнено/не заполнено» и
маска вида ••••••••7Kp2.
"""

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.main_roles import ROLE_OPERATOR, ROLE_OWNER
from app.services import configuration, credentials

router = APIRouter(tags=["settings"])


def _только_владелец(request: Request) -> None:
    if getattr(request.state, "role", None) != ROLE_OWNER:
        raise HTTPException(
            status_code=403, detail="Настройки интеграций доступны только владельцу"
        )


def _кто(request: Request) -> str:
    return str(getattr(request.state, "role", "?"))


def _прочитать_файл(содержимое: bytes) -> str:
    """Байты загруженного файла → текст. Файл не выполняется и не логируется."""
    if len(содержимое) > configuration.ПРЕДЕЛ_ФАЙЛА:
        raise HTTPException(
            status_code=413,
            detail="Файл слишком большой для .env — проверьте, что выбран нужный",
        )
    # Нулевой байт в текстовом файле не встречается, а cp1251 ниже разберёт
    # что угодно, включая картинку: без этой проверки на выбранный по ошибке
    # png человек получил бы «не нашлось строк вида КЛЮЧ=значение» вместо
    # «это не текстовый файл».
    if b"\x00" in содержимое:
        raise HTTPException(
            status_code=400,
            detail="Это не текстовый файл — выберите .env или другой текстовый",
        )
    try:
        return содержимое.decode("utf-8")
    except UnicodeDecodeError:
        try:
            # Файл, сохранённый Блокнотом на Windows, приходит в cp1251.
            return содержимое.decode("cp1251")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=400,
                detail="Это не текстовый файл — выберите .env или другой текстовый",
            ) from None


# ── Настройки: только владелец ────────────────────────────────────────────


@router.get("/api/settings/integrations")
async def интеграции(request: Request) -> dict:
    """Что настроено, что нет и какими полями это чинится."""
    _только_владелец(request)
    return configuration.обзор()


@router.post("/api/settings/import/preview")
async def предпросмотр_импорта(
    request: Request, file: UploadFile = File(...)
) -> dict:
    """Что даст этот файл. Конфигурацию не меняет — только показывает."""
    _только_владелец(request)
    текст = _прочитать_файл(await file.read())
    разобрано = configuration.разобрать_env(текст)
    if not разобрано:
        raise HTTPException(
            status_code=400,
            detail="В файле не нашлось ни одной строки вида КЛЮЧ=значение",
        )
    return configuration.предпросмотр(разобрано)


@router.post("/api/settings/import/apply")
async def применить_импорт(
    request: Request, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)
) -> dict:
    """Применить файл. Берутся только ключи, которые Директор умеет использовать."""
    _только_владелец(request)
    текст = _прочитать_файл(await file.read())
    разобрано = configuration.разобрать_env(текст)
    известные = {
        и: з for и, з in разобрано.items() if и in configuration.ВСЕ_КЛЮЧИ
    }
    if not известные:
        raise HTTPException(
            status_code=400,
            detail="В файле нет ни одного ключа, который Директор использует",
        )
    изменены = await configuration.сохранить(db, известные, _кто(request))
    return {"changed": изменены, **configuration.обзор()}


@router.post("/api/settings/save")
async def сохранить_вручную(
    request: Request, body: dict = Body(...), db: AsyncSession = Depends(get_db)
) -> dict:
    """Сохранить значения из формы.

    Пустое поле означает «не менять»: форма присылает незаполненными все
    поля, которых человек не трогал, и иначе правка номера филиала стирала
    бы токены. Для стирания есть /api/settings/reset.
    """
    _только_владелец(request)
    значения = body.get("values")
    if not isinstance(значения, dict):
        raise HTTPException(status_code=400, detail="Нет значений для сохранения")

    # Маска обратно как новое значение не принимается никогда: иначе
    # «сохранить», нажатое без правок, записало бы в токен строку из точек.
    очищенные = {
        str(и): str(з or "")
        for и, з in значения.items()
        if not str(з or "").strip().startswith("•")
    }
    изменены = await configuration.сохранить(db, очищенные, _кто(request))
    return {"changed": изменены, **configuration.обзор()}


@router.post("/api/settings/reset")
async def сбросить_ключ(
    request: Request, body: dict = Body(...), db: AsyncSession = Depends(get_db)
) -> dict:
    """Убрать значение. Интеграция становится ненастроенной, приложение живёт."""
    _только_владелец(request)
    имя = str(body.get("key") or "").strip()
    try:
        await configuration.сбросить(db, имя, _кто(request))
    except ValueError as сбой:
        raise HTTPException(status_code=400, detail=str(сбой)) from None
    return configuration.обзор()


@router.post("/api/settings/test/{интеграция}")
async def проверить_подключение(request: Request, интеграция: str) -> dict:
    """Сходить в сервис и проверить, что ключи рабочие."""
    _только_владелец(request)
    try:
        return await configuration.проверить(интеграция)
    except ValueError as сбой:
        raise HTTPException(status_code=404, detail=str(сбой)) from None


@router.post("/api/settings/yclients/user-token")
async def получить_токен_yclients(
    request: Request, body: dict = Body(...), db: AsyncSession = Depends(get_db)
) -> dict:
    """Получить пользовательский токен по логину и паролю кабинета YCLIENTS.

    Логин и пароль нигде не остаются — ни в базе, ни в журнале. Сохраняется
    только выданный токен.
    """
    _только_владелец(request)
    try:
        имя = await configuration.получить_пользовательский_токен(
            db,
            str(body.get("login") or ""),
            str(body.get("password") or ""),
            _кто(request),
        )
    except ValueError as сбой:
        raise HTTPException(status_code=400, detail=str(сбой)) from None
    except RuntimeError as сбой:
        raise HTTPException(status_code=502, detail=str(сбой)) from None
    return {"ok": True, "message": f"Токен получен и сохранён. Выдан для: {имя}", **configuration.обзор()}


@router.post("/api/settings/telegram/test-message")
async def тестовое_сообщение(
    request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    """Отправить в чат пробное сообщение. Само по себе не отправляется никогда."""
    _только_владелец(request)
    from app.services import telegram

    try:
        await telegram.отправить_сообщение(
            "РублЪ Директор: проверка связи. Если вы это видите — всё настроено.",
            session=db,
        )
    except telegram.TelegramNotConfiguredError as сбой:
        raise HTTPException(status_code=400, detail=str(сбой)) from None
    except telegram.TelegramSendError as сбой:
        raise HTTPException(status_code=502, detail=str(сбой)) from None
    return {"ok": True, "message": "Сообщение отправлено"}


@router.get("/api/settings/audit")
async def журнал_изменений(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Кто, когда и какой параметр менял. Значений здесь нет и не будет."""
    _только_владелец(request)
    return {"entries": await configuration.журнал(db)}


@router.post("/api/settings/account")
async def сменить_учётную_запись(
    request: Request, body: dict = Body(...), db: AsyncSession = Depends(get_db)
) -> dict:
    """Завести или сменить логин и пароль владельца либо администратора."""
    _только_владелец(request)
    роль = str(body.get("role") or "").strip()
    if роль not in (ROLE_OWNER, ROLE_OPERATOR):
        raise HTTPException(status_code=400, detail="Неизвестная роль")
    try:
        await credentials.завести(
            db, роль, str(body.get("login") or ""), str(body.get("password") or "")
        )
    except ValueError as сбой:
        raise HTTPException(status_code=400, detail=str(сбой)) from None
    return {"ok": True}


# ── Мастер первичной настройки ─────────────────────────────────────────────


def _только_до_настройки() -> None:
    from app.main import настройка_не_закончена

    if not настройка_не_закончена():
        raise HTTPException(
            status_code=409,
            detail="Директор уже настроен — войдите под своей учётной записью",
        )


def _код_из_запроса(request: Request, body: dict | None = None) -> None:
    код = request.headers.get("X-Setup-Code") or (body or {}).get("code") or ""
    if not credentials.код_подходит(str(код)):
        raise HTTPException(
            status_code=403,
            detail="Код не подошёл. Он напечатан в окне установки и в файле "
            "output/код-настройки.txt рядом с программой.",
        )


@router.get("/api/setup/state")
async def состояние_настройки() -> dict:
    """Нужна ли первичная настройка. Единственный маршрут без кода.

    Секретов не содержит — по нему интерфейс решает, показывать мастер или
    обычную страницу входа.
    """
    from app.main import настройка_не_закончена

    return {"setup_required": настройка_не_закончена()}


@router.post("/api/setup/check-code")
async def проверить_код(body: dict = Body(default={})) -> dict:
    _только_до_настройки()
    код = str(body.get("code") or "")
    if not credentials.код_подходит(код):
        raise HTTPException(status_code=403, detail="Код не подошёл")
    return {"ok": True}


@router.post("/api/setup/owner")
async def завести_владельца(
    request: Request, body: dict = Body(...), db: AsyncSession = Depends(get_db)
) -> dict:
    """Первый шаг мастера: владелец придумывает себе логин и пароль."""
    from app.main import убрать_код_настройки

    _только_до_настройки()
    _код_из_запроса(request, body)
    try:
        await credentials.завести(
            db, ROLE_OWNER, str(body.get("login") or ""), str(body.get("password") or "")
        )
    except ValueError as сбой:
        raise HTTPException(status_code=400, detail=str(сбой)) from None
    убрать_код_настройки()
    return {"ok": True}
