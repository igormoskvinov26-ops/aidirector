"""Rubl AI Director — FastAPI Application."""

import base64
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes.ai import router as ai_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.employees import router as employees_router
from app.api.routes.sync import router as sync_router
from app.config import settings
from app.database import init_db

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)

        auth = request.headers.get("Authorization")
        if not auth or not auth.startswith("Basic "):
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Rubl Director"'},
                content="Authentication required",
            )

        try:
            decoded = base64.b64decode(auth[6:]).decode()
            login, password = decoded.split(":", 1)
        except Exception:
            return Response(status_code=401, content="Invalid credentials")

        if not secrets.compare_digest(login, settings.admin_login) or \
           not secrets.compare_digest(password, settings.admin_password):
            return Response(status_code=401, content="Invalid credentials")

        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Rubl AI Director...")
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.warning(f"Database not available, running without DB: {e}")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="Rubl AI Director",
    version="1.0.0",
    description="AI-powered management system for Rubl Barbershop",
    lifespan=lifespan,
)

app.add_middleware(BasicAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ai_router)
app.include_router(dashboard_router)
app.include_router(employees_router)
app.include_router(sync_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/info")
async def info() -> dict[str, int | str]:
    return {
        "company_id": settings.yclients_company_id,
        "sync_interval_minutes": settings.sync_interval_minutes,
    }


if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    logger.info(f"Serving static files from {STATIC_DIR}")
else:
    logger.info("No static directory, API-only mode")
