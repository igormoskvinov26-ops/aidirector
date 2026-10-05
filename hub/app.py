"""Общий сервер: хранилище документов для синхронизации установок + витрина
для владельца (дашборд на телефоне).

Намеренно не знает ничего о клиентах, записях и телефонах — только то, что
установки сами решили прислать (см. backend/app/services/hub.py). Документ =
строковый ключ + произвольный JSON, версия — сквозной счётчик seq на сервере.

Протокол (тот же, что ждёт backend/app/services/hub.py и его тесты):
  GET  /v1/health              — 200, если ключ верный
  PUT  /v1/doc/{key}           — {"value": ..., "base_seq": N} -> {"seq": M}
                                  409, если текущий seq документа != base_seq
  GET  /v1/changes?since=N     — {"seq": текущий максимум, "docs": [...]}
  GET  /v1/dashboard           — последний docs["owner_dashboard"].value,
                                  витрина для PWA владельца (только агрегаты)

Хранилище — один файл SQLite (HUB_DB), без привязки к бизнес-моделям
Директора/Пульта: сервер не разбирает содержимое документов, кроме как для
отдачи /v1/dashboard.
"""

import json
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

HUB_TOKEN = os.environ.get("HUB_TOKEN", "")
HUB_DB = os.environ.get("HUB_DB", str(Path(__file__).resolve().parent / "hub.db"))
DASHBOARD_KEY = "owner_dashboard"

app = FastAPI(title="РублЪ Пульт — общий сервер")

_lock = threading.Lock()
_conn = sqlite3.connect(HUB_DB, check_same_thread=False)
_conn.execute(
    """CREATE TABLE IF NOT EXISTS docs (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        seq INTEGER NOT NULL,
        writer TEXT,
        updated_at TEXT NOT NULL
    )"""
)
_conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_seq ON docs(seq)")
_conn.commit()


def _проверить_ключ(request: Request) -> None:
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else ""
    if not HUB_TOKEN or token != HUB_TOKEN:
        raise HTTPException(status_code=401, detail="неверный или отсутствующий ключ")


def _макс_seq() -> int:
    row = _conn.execute("SELECT COALESCE(MAX(seq), 0) FROM docs").fetchone()
    return row[0]


@app.get("/v1/health")
def health(request: Request) -> dict:
    _проверить_ключ(request)
    return {"ok": True}


@app.put("/v1/doc/{key:path}")
def put_doc(key: str, body: dict[str, Any], request: Request) -> JSONResponse:
    _проверить_ключ(request)
    value = body["value"]
    base_seq = int(body.get("base_seq") or 0)
    writer = request.headers.get("x-writer", "")
    with _lock:
        row = _conn.execute("SELECT seq FROM docs WHERE key = ?", (key,)).fetchone()
        текущий = row[0] if row else 0
        if текущий != base_seq:
            return JSONResponse({"detail": "конфликт версий"}, status_code=409)
        новый_seq = _макс_seq() + 1
        _conn.execute(
            "INSERT INTO docs (key, value, seq, writer, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, seq = excluded.seq, "
            "writer = excluded.writer, updated_at = excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), новый_seq, writer,
             datetime.now(UTC).isoformat()),
        )
        _conn.commit()
    return JSONResponse({"seq": новый_seq})


@app.get("/v1/changes")
def changes(request: Request, since: int = 0) -> dict:
    _проверить_ключ(request)
    rows = _conn.execute(
        "SELECT key, value, seq FROM docs WHERE seq > ? ORDER BY seq", (since,)
    ).fetchall()
    docs = [{"key": k, "value": json.loads(v), "seq": s} for k, v, s in rows]
    return {"seq": max(since, _макс_seq()), "docs": docs}


@app.get("/v1/dashboard")
def dashboard(request: Request) -> dict:
    _проверить_ключ(request)
    row = _conn.execute(
        "SELECT value, updated_at FROM docs WHERE key = ?", (DASHBOARD_KEY,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ещё не синхронизировалось")
    value, updated_at = row
    return {**json.loads(value), "updated_at": updated_at}


_СТАТИКА = Path(__file__).resolve().parent / "dashboard"
if _СТАТИКА.is_dir():
    app.mount("/", StaticFiles(directory=str(_СТАТИКА), html=True), name="dashboard")
