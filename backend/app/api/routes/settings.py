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

from loguru import logger
from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.main_roles import ROLE_OPERATOR, ROLE_OWNER
from app.config import settings
from app.services import branches, configuration, credentials, salon

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
    """Применить файл. Берутся только ключи, которые Пульт умеет использовать."""
    _только_владелец(request)
    текст = _прочитать_файл(await file.read())
    разобрано = configuration.разобрать_env(текст)
    известные = {
        и: з for и, з in разобрано.items() if и in configuration.ВСЕ_КЛЮЧИ
    }
    if not известные:
        raise HTTPException(
            status_code=400,
            detail="В файле нет ни одного ключа, который Пульт использует",
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


@router.get("/api/settings/hub/status")
async def статус_сервера(request: Request) -> dict:
    """Последний обмен с общим сервером: когда, успешно ли, сколько передано."""
    _только_владелец(request)
    from app.services import hub

    return {"configured": hub.настроен(), **hub.status}


# Имена параметров пути — только латиницей: Starlette кириллическое имя не
# распознаёт и считает адрес буквальной строкой, маршрут молча не находится.
@router.post("/api/settings/test/{integration}")
async def проверить_подключение(request: Request, integration: str) -> dict:
    """Сходить в сервис и проверить, что ключи рабочие."""
    _только_владелец(request)
    try:
        return await configuration.проверить(integration)
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
            "РублЪ Пульт: проверка связи. Если вы это видите — всё настроено.",
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
            db, роль, str(body.get("login") or ""), str(body.get("password") or ""),
            ветка=not branches.главный(),
        )
    except ValueError as сбой:
        raise HTTPException(status_code=400, detail=str(сбой)) from None
    return {"ok": True}


@router.get("/api/settings/top-account")
async def учётка_владельца(request: Request) -> dict:
    _главный_владелец(request)
    return {"exists": credentials.заведён("top"), "login": credentials.логин("top")}


@router.post("/api/settings/top-account")
async def завести_владельца_отдельно(
    request: Request, body: dict = Body(...), db: AsyncSession = Depends(get_db)
) -> dict:
    """Отдельная учётка Владельца. После неё главный вход — Управляющий:
    без «Контроля финансов» и без филиалов."""
    _главный_владелец(request)
    try:
        await credentials.завести(
            db, "top", str(body.get("login") or ""), str(body.get("password") or "")
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
            detail="Пульт уже настроен — войдите под своей учётной записью",
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


# ── Заведение: название, логотип, барберы ─────────────────────────────────


def _логотип():
    return settings.output_dir / "logo.png"


ТЕМЫ_ФОНА = ("light", "dark")


def _фон(тема: str):
    if тема not in ТЕМЫ_ФОНА:
        raise HTTPException(status_code=404, detail="Тема: light или dark")
    return settings.output_dir / f"bg-{тема}.jpg"


def _фоны() -> dict:
    """Какие свои фоны загружены; v — метка для сброса кэша браузера."""
    out: dict = {}
    for тема in ТЕМЫ_ФОНА:
        путь = settings.output_dir / f"bg-{тема}.jpg"
        out[тема] = int(путь.stat().st_mtime) if путь.exists() else None
    return out


@router.get("/api/salon")
async def заведение() -> dict:
    """Название, адрес записи, свой логотип и фоны. Читают все роли."""
    return {**salon.обзор(), "has_logo": _логотип().exists(), "backgrounds": _фоны()}


@router.get("/api/salon/background/{theme}")
async def фон(theme: str) -> Response:
    путь = _фон(theme)
    if not путь.exists():
        raise HTTPException(status_code=404, detail="Свой фон не загружен")
    return Response(путь.read_bytes(), media_type="image/jpeg",
                    headers={"Cache-Control": "max-age=31536000"})


@router.post("/api/salon/background/{theme}")
async def загрузить_фон(theme: str, request: Request, file: UploadFile = File(...)) -> dict:
    """Фото под карточками. Ужимаем до 2560 px и JPEG — иначе страница грузится долго."""
    _только_владелец(request)
    путь = _фон(theme)
    import io

    from PIL import Image, ImageOps

    данные = await file.read()
    if len(данные) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Фото больше 25 МБ")
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(данные))).convert("RGB")
        img.thumbnail((2560, 2560))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85, optimize=True, progressive=True)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Это не картинка") from None
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    путь.write_bytes(buf.getvalue())
    return {"ok": True, "backgrounds": _фоны()}


@router.delete("/api/salon/background/{theme}")
async def убрать_фон(theme: str, request: Request) -> dict:
    """Вернуть встроенный фон."""
    _только_владелец(request)
    _фон(theme).unlink(missing_ok=True)
    return {"ok": True, "backgrounds": _фоны()}


@router.get("/api/salon/logo")
async def логотип() -> Response:
    if not _логотип().exists():
        raise HTTPException(status_code=404, detail="Логотип не загружен")
    return Response(_логотип().read_bytes(), media_type="image/png",
                    headers={"Cache-Control": "no-cache"})


@router.post("/api/salon/logo")
async def загрузить_логотип(request: Request, file: UploadFile = File(...)) -> dict:
    _только_владелец(request)
    import io

    from PIL import Image

    данные = await file.read()
    if len(данные) > 4 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Логотип больше 4 МБ")
    try:
        img = Image.open(io.BytesIO(данные)).convert("RGBA")
        рамка = img.getchannel("A").getbbox()  # прозрачные поля вокруг рисунка делают логотип мелким
        if рамка:
            img = img.crop(рамка)
        img.thumbnail((512, 512))
        buf = io.BytesIO()
        img.save(buf, "PNG")
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Это не картинка") from None
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    _логотип().write_bytes(buf.getvalue())
    return {"ok": True}


@router.post("/api/salon")
async def сохранить_заведение(
    request: Request, body: dict = Body(...), db: AsyncSession = Depends(get_db)
) -> dict:
    _только_владелец(request)
    try:
        await salon.сохранить(db, salon_name=body.get("name"), booking=body.get("booking_url"))
    except ValueError as сбой:
        raise HTTPException(status_code=400, detail=str(сбой)) from None
    return {**salon.обзор(), "has_logo": _логотип().exists()}


@router.get("/api/settings/barbers")
async def барберы(request: Request) -> dict:
    """Сотрудники YCLIENTS и отметки «барбер» со ставками."""
    _только_владелец(request)
    from app.api.yclients import YClientsClient

    try:
        async with YClientsClient() as client:
            staff = await client.get_active_staff()
    except Exception as сбой:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"YCLIENTS не отвечает: {сбой}") from None
    return {
        "staff": [{"id": s["id"], "name": s.get("name", "")} for s in staff
                  if not salon.служебный(s.get("name"))],
        "barbers": settings.barber_payroll_rules,
    }


@router.post("/api/settings/barbers")
async def сохранить_барберов(
    request: Request, body: dict = Body(...), db: AsyncSession = Depends(get_db)
) -> dict:
    _только_владелец(request)
    try:
        await salon.сохранить(db, barbers=body.get("barbers") or [])
    except (ValueError, KeyError, TypeError) as сбой:
        raise HTTPException(status_code=400, detail=f"Не удалось сохранить: {сбой}") from None
    return {"barbers": settings.barber_payroll_rules}


# ── Филиалы: только главный владелец ───────────────────────────────────────


def _главный_владелец(request: Request) -> None:
    if not getattr(request.state, "top", False):
        raise HTTPException(status_code=403, detail="Филиалами управляет только Владелец")


@router.get("/api/branches")
async def филиалы(request: Request) -> dict:
    """Список для переключателя. Остальным ролям переключатель не нужен."""
    if not getattr(request.state, "top", False):
        return {"active": branches.active, "branches": [], "can_manage": False}
    return {**branches.список(), "can_manage": True}


@router.post("/api/branches/switch")
async def переключить_филиал(request: Request, body: dict = Body(...)) -> dict:
    _главный_владелец(request)
    try:
        await branches.переключить(str(body.get("id") or ""))
    except KeyError:
        raise HTTPException(status_code=404, detail="Нет такого филиала") from None
    except RuntimeError as сбой:
        raise HTTPException(status_code=409, detail=str(сбой)) from None
    return branches.список()


@router.post("/api/branches")
async def добавить_филиал(request: Request, body: dict = Body(...)) -> dict:
    _главный_владелец(request)
    try:
        return await branches.создать(
            str(body.get("name") or ""),
            (str(body.get("admin_login") or ""), str(body.get("admin_password") or "")),
            (str(body.get("manager_login") or ""), str(body.get("manager_password") or "")),
        )
    except ValueError as сбой:
        raise HTTPException(status_code=400, detail=str(сбой)) from None
    except RuntimeError as сбой:
        raise HTTPException(status_code=409, detail=str(сбой)) from None
    except Exception as сбой:  # noqa: BLE001 — база не создалась: сказать человеку, не 500
        logger.exception("филиал не создан")
        raise HTTPException(status_code=500, detail=f"Не удалось создать филиал: {type(сбой).__name__}") from None


_ЛИЧНОЕ = ("phone", "email", "login", "password", "token", "avatar", "image", "info", "comment")


@router.get("/api/settings/staff-flags")
async def признаки_сотрудников(request: Request) -> dict:
    """Какие поля у сотрудников в YCLIENTS и какое из них отличает барберов.

    Признак-кандидат: поле, у которого у всех барберов Пульта значение «истина»
    (непустое), а у остальных сотрудников «ложь» (пустое). Личные данные не отдаются.
    """
    _только_владелец(request)
    from app.api.yclients import YClientsClient

    try:
        async with YClientsClient() as client:
            staff = await client.get_staff()
    except Exception as сбой:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"YCLIENTS не отвечает: {сбой}") from None
    barber_ids = {int(b["staff_id"]) for b in settings.barber_payroll_rules}
    rows, fields = [], {}
    for s in staff:
        flags = {k: v for k, v in s.items()
                 if isinstance(v, (bool, int)) and not any(w in k.lower() for w in _ЛИЧНОЕ)}
        for k, v in s.items():
            if isinstance(v, (list, dict)) and not any(w in k.lower() for w in _ЛИЧНОЕ):
                flags[k + " (есть данные)"] = bool(v)
        rows.append({"id": s.get("id"), "name": s.get("name"), "barber": s.get("id") in barber_ids, "flags": flags})
        for k in flags:
            fields.setdefault(k, []).append((s.get("id") in barber_ids, bool(flags[k])))
    candidates = [k for k, vals in fields.items()
                  if len(vals) == len(rows) and all(is_b == val for is_b, val in vals)]
    return {"staff": rows, "candidates": candidates}
