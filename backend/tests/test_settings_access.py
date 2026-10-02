"""Доступ к разделу настроек и поведение приложения без ключей.

Проверка прав живёт на сервере, а не в интерфейсе: спрятанная кнопка не
мешает обратиться к адресу напрямую, а за этими адресами лежат токены.

Отдельно закреплено поведение режима первичной настройки: пока владельца
нет, открыт только мастер, всё остальное отвечает «требуется настройка» —
а не пускает без пароля.
"""

import base64

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.routes.settings import router as settings_router
from app.config import settings
from app.main import BasicAuthMiddleware
from app.main_roles import ROLE_MASTER, ROLE_OPERATOR, ROLE_OWNER
from app.services import configuration, credentials


def _auth(login: str, password: str) -> dict[str, str]:
    токен = base64.b64encode(f"{login}:{password}".encode()).decode()
    return {"Authorization": f"Basic {токен}"}


ВЛАДЕЛЕЦ = _auth(settings.owner_login, settings.owner_password)
АДМИНИСТРАТОР = _auth(settings.operator_login, settings.operator_password)
МАСТЕР = _auth("test-master", "test-master-password")


@pytest.fixture(autouse=True)
def чистый_кэш(monkeypatch):
    """Ни одного заданного ключа: проверяем, что их и не появится."""
    monkeypatch.setattr(configuration, "ИЗ_ОКРУЖЕНИЯ_ПРОЦЕССА", frozenset())
    monkeypatch.setattr(configuration, "_управляемые", {})
    monkeypatch.setattr(configuration, "_последняя_ошибка", {})
    monkeypatch.setattr(credentials, "_учётные", {})
    for поле in (
        "yclients_partner_token",
        "yclients_user_token",
        "telegram_bot_token",
        "telegram_chat_id",
    ):
        monkeypatch.setattr(settings, поле, "")
    monkeypatch.setattr(settings, "yclients_company_id", 0)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.add_middleware(BasicAuthMiddleware)
    app.include_router(settings_router)

    @app.get("/api/finance/daily")
    async def finance() -> dict:
        return {"revenue": 1}

    @app.get("/")
    async def страница() -> dict:
        return {"page": "index"}

    return TestClient(app)


# ── Права (раздел 13 ТЗ, сценарий 9) ──────────────────────────────────────


def test_владелец_видит_настройки(client: TestClient):
    assert client.get("/api/settings/integrations", headers=ВЛАДЕЛЕЦ).status_code == 200


@pytest.mark.parametrize("кто", [АДМИНИСТРАТОР, МАСТЕР])
def test_остальные_роли_к_настройкам_не_допускаются(client: TestClient, кто):
    for адрес in ("/api/settings/integrations", "/api/settings/audit"):
        ответ = client.get(адрес, headers=кто)
        assert ответ.status_code == 403, адрес


@pytest.mark.parametrize("кто", [АДМИНИСТРАТОР, МАСТЕР])
def test_остальные_роли_не_меняют_ключи(client: TestClient, кто):
    ответ = client.post(
        "/api/settings/save",
        headers=кто,
        json={"values": {"YCLIENTS_PARTNER_TOKEN": "чужой"}},
    )
    assert ответ.status_code == 403
    assert configuration.значение("YCLIENTS_PARTNER_TOKEN") == ""


def test_без_пароля_настройки_не_открываются(client: TestClient):
    assert client.get("/api/settings/integrations").status_code == 401


# ── Маска не принимается как значение (раздел 9 ТЗ, сценарий 11) ──────────


def test_маска_обратно_не_сохраняется(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        configuration, "_управляемые", {"YCLIENTS_PARTNER_TOKEN": "настоящий-7Kp2"}
    )
    ответ = client.post(
        "/api/settings/save",
        headers=ВЛАДЕЛЕЦ,
        json={"values": {"YCLIENTS_PARTNER_TOKEN": "••••••••7Kp2"}},
    )
    assert ответ.status_code == 200
    assert ответ.json()["changed"] == []
    assert configuration.значение("YCLIENTS_PARTNER_TOKEN") == "настоящий-7Kp2"


# ── Ответ не содержит секретов (раздел 14 ТЗ, сценарий 10) ────────────────


def test_ответ_не_содержит_секрета(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        configuration,
        "_управляемые",
        {"YCLIENTS_PARTNER_TOKEN": "очень-секретный-токен-7Kp2"},
    )
    тело = client.get("/api/settings/integrations", headers=ВЛАДЕЛЕЦ).text
    assert "очень-секретный" not in тело
    assert "7Kp2" in тело  # хвост маски показывается — по нему узнают свой ключ


# ── Импорт файла (раздел 6 ТЗ, сценарии 4 и 6) ────────────────────────────


def test_предпросмотр_не_меняет_настройки(client: TestClient):
    файл = b"YCLIENTS_PARTNER_TOKEN=partner-1234\nAWS_SECRET_KEY=chuzhoe\n"
    ответ = client.post(
        "/api/settings/import/preview",
        headers=ВЛАДЕЛЕЦ,
        files={"file": (".env", файл, "text/plain")},
    )
    assert ответ.status_code == 200
    тело = ответ.json()
    assert тело["unknown"] == ["AWS_SECRET_KEY"]
    # Файл показан, но не применён.
    assert configuration.значение("YCLIENTS_PARTNER_TOKEN") == ""


def test_слишком_большой_файл_отвергается(client: TestClient):
    громадный = b"X=1\n" * 200_000
    ответ = client.post(
        "/api/settings/import/preview",
        headers=ВЛАДЕЛЕЦ,
        files={"file": ("big.env", громадный, "text/plain")},
    )
    assert ответ.status_code == 413


def test_двоичный_файл_отвергается_понятно(client: TestClient):
    ответ = client.post(
        "/api/settings/import/preview",
        headers=ВЛАДЕЛЕЦ,
        files={"file": ("photo.png", b"\x89PNG\x00\xff\xfe\xfd", "image/png")},
    )
    assert ответ.status_code == 400
    assert "текстовый" in ответ.json()["detail"]


def test_файл_без_нужных_ключей_отвергается(client: TestClient):
    ответ = client.post(
        "/api/settings/import/apply",
        headers=ВЛАДЕЛЕЦ,
        files={"file": (".env", b"AWS_SECRET_KEY=chuzhoe\n", "text/plain")},
    )
    assert ответ.status_code == 400


# ── Режим первичной настройки (раздел 17 ТЗ, сценарий 2) ──────────────────


@pytest.fixture
def без_владельца(monkeypatch):
    for поле in ("owner_login", "owner_password", "operator_login", "operator_password"):
        monkeypatch.setattr(settings, поле, "")
    monkeypatch.setattr(settings, "master_accounts", [])


def test_в_режиме_настройки_api_отвечает_503(client: TestClient, без_владельца):
    ответ = client.get("/api/finance/daily")
    assert ответ.status_code == 503
    assert ответ.json()["setup_required"] is True


def test_в_режиме_настройки_страница_отдаётся(client: TestClient, без_владельца):
    """Иначе мастер настройки не на чем открыть."""
    assert client.get("/").status_code == 200


def test_в_режиме_настройки_мастер_открыт(client: TestClient, без_владельца):
    ответ = client.get("/api/setup/state")
    assert ответ.status_code == 200
    assert ответ.json()["setup_required"] is True


def test_мастер_без_кода_не_заводит_владельца(client: TestClient, без_владельца):
    ответ = client.post(
        "/api/setup/owner",
        json={"login": "igor", "password": "длинный-пароль-владельца"},
    )
    assert ответ.status_code == 403
    assert credentials.заведён(ROLE_OWNER) is False


def test_настроенный_директор_закрывает_мастер(client: TestClient):
    """Владелец есть — открытая на время настройки дверь должна закрыться."""
    ответ = client.post(
        "/api/setup/owner",
        headers=ВЛАДЕЛЕЦ,
        json={"login": "chuzhoy", "password": "длинный-пароль-чужого"},
    )
    assert ответ.status_code == 409


def test_состояние_настройки_не_требует_пароля_но_и_не_выдаёт_лишнего(
    client: TestClient,
):
    ответ = client.get("/api/setup/state", headers=ВЛАДЕЛЕЦ)
    assert ответ.status_code == 200
    assert ответ.json() == {"setup_required": False}


# ── Роли в списке разрешённых не расширились ──────────────────────────────


def test_настройки_не_попали_в_список_доступного_остальным():
    """Защита от случайного расширения прав при правке main.py."""
    from app.main import MASTER_API_PREFIXES, OPERATOR_API_PREFIXES

    for префикс in (*OPERATOR_API_PREFIXES, *MASTER_API_PREFIXES):
        assert not префикс.startswith("/api/settings")
        assert not префикс.startswith("/api/setup")


def test_роли_не_перепутаны():
    assert ROLE_OWNER != ROLE_OPERATOR != ROLE_MASTER
