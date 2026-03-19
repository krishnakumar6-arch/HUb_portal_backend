from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.models import ETLLog, User
from app.middleware.auth import require_admin

router = APIRouter(prefix="/etl", tags=["etl"])

@router.post("/trigger")
async def trigger_etl(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Manually trigger an ETL sync — runs in background"""
    from etl.pipeline import run_etl
    background_tasks.add_task(run_etl, triggered_by="manual_api")
    return {"message": "ETL sync started in background. Check /etl/logs for status."}

@router.get("/logs")
async def get_etl_logs(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Last N ETL run logs"""
    result = await db.execute(
        select(ETLLog).order_by(ETLLog.started_at.desc()).limit(limit)
    )
    logs = result.scalars().all()
    return [
        {
            "id": str(log.id),
            "started_at": str(log.started_at),
            "finished_at": str(log.finished_at) if log.finished_at else None,
            "status": log.status,
            "rows_processed": log.rows_processed,
            "rows_inserted": log.rows_inserted,
            "error": log.error_message,
            "triggered_by": log.triggered_by,
        }
        for log in logs
    ]
