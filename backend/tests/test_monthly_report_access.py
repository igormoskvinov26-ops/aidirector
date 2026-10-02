"""Месячный отчёт: права доступа и совпадение миграции с моделями."""

import base64
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.monthly_report import router
from app.config import settings
from app.main import BasicAuthMiddleware
from app.models.models import ContactAttempt, MonthlyReportSnapshot, ReportSetting


def _auth(login: str, password: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{login}:{password}".encode()).decode()}


ВЛАДЕЛЕЦ = _auth(settings.owner_login, settings.owner_password)
ОПЕРАТОР = _auth(settings.operator_login, settings.operator_password)
МАСТЕР = _auth("test-master", "test-master-password")


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.add_middleware(BasicAuthMiddleware)
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("кто", [ОПЕРАТОР, МАСТЕР])
@pytest.mark.parametrize(
    "адрес",
    ["/api/monthly-report?month=2026-09", "/api/monthly-report/settings",
     "/api/monthly-report/drilldown?month=2026-09&kind=made", "/api/monthly-report/fields-probe"],
)
def test_отчёт_только_владельцу(client: TestClient, кто, адрес):
    assert client.get(адрес, headers=кто).status_code == 403


def test_без_пароля_401(client: TestClient):
    assert client.get("/api/monthly-report?month=2026-09").status_code == 401


def test_месяц_обязателен_и_проверяется(client: TestClient):
    assert client.get("/api/monthly-report", headers=ВЛАДЕЛЕЦ).status_code == 422
    assert client.get("/api/monthly-report?month=сентябрь", headers=ВЛАДЕЛЕЦ).status_code == 422
    assert client.get("/api/monthly-report?month=2099-01", headers=ВЛАДЕЛЕЦ).status_code == 422


@pytest.mark.parametrize("кто", [ОПЕРАТОР, МАСТЕР])
def test_оператор_и_мастер_не_меняют_настройки_отчёта(client: TestClient, кто):
    assert client.post("/api/monthly-report/settings", headers=кто, json={}).status_code == 403
    assert client.post("/api/monthly-report/verify", headers=кто).status_code == 403


МИГРАЦИЯ = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "0010_monthly_report.py"


def test_миграция_совпадает_с_моделями():
    текст = МИГРАЦИЯ.read_text(encoding="utf-8")
    for модель in (ReportSetting, MonthlyReportSnapshot):
        начало = текст.index(f'"{модель.__tablename__}",')
        конец = текст.index("\n        )", начало)
        из_миграции = set(re.findall(r'sa\.Column\(\s*"([a-z_]+)"', текст[начало:конец]))
        assert из_миграции == {c.name for c in модель.__table__.columns}, модель.__tablename__
    блок = текст[текст.index("НОВЫЕ_КОЛОНКИ = ("):текст.index("\n)\n", текст.index("НОВЫЕ_КОЛОНКИ = ("))]
    новые = set(re.findall(r'\("([a-z_]+)", sa\.', блок))
    есть_в_модели = {c.name for c in ContactAttempt.__table__.columns}
    assert новые and новые <= есть_в_модели, новые - есть_в_модели
