"""Разграничение доступа между двумя учётными записями.

На странице обзвона лежат имена и телефоны клиентов, поэтому проверяется не
только то, что оператор входит, но и то, что дальше базы обзвона он не идёт.
Отдельно закреплено поведение по умолчанию: новый маршрут под /api/ закрыт
для оператора, пока его явно не внесли в список разрешённых.
"""

import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.main import BasicAuthMiddleware, _resolve_identity
from app.main_roles import ROLE_MASTER, ROLE_OPERATOR, ROLE_OWNER


def _auth(login: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{login}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


OWNER = _auth(settings.owner_login, settings.owner_password)
OPERATOR = _auth(settings.operator_login, settings.operator_password)


@pytest.fixture
def client() -> TestClient:
    """Приложение с той же прослойкой авторизации, но без базы и роутеров."""
    app = FastAPI()
    app.add_middleware(BasicAuthMiddleware)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/client-base/tasks")
    async def tasks() -> dict:
        return {"tasks": []}

    @app.get("/api/finance/daily")
    async def finance() -> dict:
        return {"revenue": 1}

    @app.get("/api/barbers/payroll")
    async def payroll() -> dict:
        return {"masters": []}

    @app.get("/api/brand-new-route")
    async def brand_new() -> dict:
        return {"ok": True}

    @app.get("/")
    async def index() -> dict:
        return {"page": "spa"}

    return TestClient(app)


def test_resolve_identity_distinguishes_accounts():
    assert _resolve_identity(settings.owner_login, settings.owner_password) == (ROLE_OWNER, None)
    assert _resolve_identity(settings.operator_login, settings.operator_password) == (
        ROLE_OPERATOR,
        None,
    )


def test_resolve_identity_rejects_crossed_credentials():
    """Логин одной записи с паролем другой не должен подходить никуда."""
    assert _resolve_identity(settings.owner_login, settings.operator_password) is None
    assert _resolve_identity(settings.operator_login, settings.owner_password) is None


def test_master_account_carries_its_staff_id(monkeypatch):
    """Роль мастера бесполезна без привязки: иначе непонятно, чью зарплату дать."""
    monkeypatch.setattr(
        settings,
        "master_accounts",
        [{"login": "ksenia", "password": "master-password-x", "staff_id": 5659614}],
    )
    assert _resolve_identity("ksenia", "master-password-x") == (ROLE_MASTER, 5659614)
    assert _resolve_identity("ksenia", "wrong-password") is None


def test_health_is_public(client):
    assert client.get("/health").status_code == 200


def test_no_credentials_rejected(client):
    r = client.get("/api/client-base/tasks")
    assert r.status_code == 401
    assert "Basic" in r.headers.get("WWW-Authenticate", "")


def test_wrong_password_rejected(client):
    r = client.get("/api/client-base/tasks", headers=_auth(settings.owner_login, "nope"))
    assert r.status_code == 401


def test_owner_reaches_everything(client):
    assert client.get("/api/client-base/tasks", headers=OWNER).status_code == 200
    assert client.get("/api/finance/daily", headers=OWNER).status_code == 200
    assert client.get("/api/brand-new-route", headers=OWNER).status_code == 200


def test_operator_reaches_call_base(client):
    assert client.get("/api/client-base/tasks", headers=OPERATOR).status_code == 200


def test_operator_denied_finance(client):
    r = client.get("/api/finance/daily", headers=OPERATOR)
    assert r.status_code == 403


def test_operator_reaches_payroll(client):
    """Администратор видит зарплату всех — это его работа."""
    assert client.get("/api/barbers/payroll", headers=OPERATOR).status_code == 200


def test_master_reaches_only_payroll(client, monkeypatch):
    monkeypatch.setattr(
        settings,
        "master_accounts",
        [{"login": "ksenia", "password": "master-password-x", "staff_id": 5659614}],
    )
    master = _auth("ksenia", "master-password-x")
    assert client.get("/api/barbers/payroll", headers=master).status_code == 200
    assert client.get("/api/finance/daily", headers=master).status_code == 403
    assert client.get("/api/client-base/tasks", headers=master).status_code == 403
    assert client.get("/api/brand-new-route", headers=master).status_code == 403


def test_unlisted_route_is_closed_for_operator_by_default(client):
    """Забыть закрыть новый маршрут нельзя: он закрыт, пока не открыт явно."""
    assert client.get("/api/brand-new-route", headers=OPERATOR).status_code == 403


def test_operator_still_gets_the_page_itself(client):
    """Статику интерфейса оператор получать обязан, иначе ему нечего открыть."""
    assert client.get("/", headers=OPERATOR).status_code == 200
