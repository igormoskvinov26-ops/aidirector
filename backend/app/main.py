"""Rubl AI Director — FastAPI Application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api.routes.ai import router as ai_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.employees import router as employees_router
from app.api.routes.sync import router as sync_router
from app.config import settings
from app.database import init_db


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
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
