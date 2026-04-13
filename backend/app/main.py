import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.api.router import api_router
from app.core.config import settings
from app.db.session import Base, engine
from app.services.automation_service import start_automation_loop, stop_automation_loop


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def _ensure_automation_columns() -> None:
    inspector = inspect(engine)
    if 'automation_settings' not in inspector.get_table_names():
        return
    existing = {column['name'] for column in inspector.get_columns('automation_settings')}
    statements = []
    if 'schedule_mode' not in existing:
        statements.append("ALTER TABLE automation_settings ADD COLUMN schedule_mode VARCHAR(20) DEFAULT 'interval'")
    if 'daily_hour' not in existing:
        statements.append('ALTER TABLE automation_settings ADD COLUMN daily_hour INTEGER')
    if 'daily_minute' not in existing:
        statements.append('ALTER TABLE automation_settings ADD COLUMN daily_minute INTEGER')
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        connection.execute(text("UPDATE automation_settings SET schedule_mode = COALESCE(schedule_mode, 'interval')"))


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    _ensure_automation_columns()
    settings.export_dir.mkdir(parents=True, exist_ok=True)
    start_automation_loop()
    try:
        yield
    finally:
        stop_automation_loop()


def _build_cors_origins() -> list[str]:
    candidates = {
        settings.frontend_url,
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    }
    return [origin for origin in candidates if origin]


app = FastAPI(title="Etimad Tender Monitor", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_build_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/")
def root():
    return {"message": "Etimad Tender Monitor API"}
