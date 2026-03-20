from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import logging

from app.config import settings
from app.routes import auth, hubs, dashboard, export, etl

log = logging.getLogger("app")
scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    from etl.pipeline import run_etl
    scheduler.add_job(
        lambda: run_etl("scheduler"),
        CronTrigger(
            hour=settings.ETL_CRON_HOUR,
            minute=settings.ETL_CRON_MINUTE,
            timezone=settings.ETL_CRON_TIMEZONE
        ),
        id="nightly_etl",
        replace_existing=True
    )
    scheduler.start()
    log.info(f"Scheduler started — ETL runs at {settings.ETL_CRON_HOUR}:{settings.ETL_CRON_MINUTE:02d} {settings.ETL_CRON_TIMEZONE}")
    yield
    scheduler.shutdown()

app = FastAPI(
    title="Hub Portal API",
    description="Shadowfax Hub Facility Expense Intelligence Platform",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS — allow all Vercel deployments + localhost ───────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # open for now — tighten after confirming domain
    allow_credentials=False,      # must be False when allow_origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(hubs.router)
app.include_router(dashboard.router)
app.include_router(export.router)
app.include_router(etl.router)

@app.get("/")
async def root():
    return {"service": "Hub Portal API", "version": "1.0.0", "status": "running", "docs": "/docs"}

@app.get("/health")
async def health():
    return {"status": "ok"}
