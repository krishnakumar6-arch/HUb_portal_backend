from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from app.database import get_db
from app.models.models import Hub, HubAggregate, Expense, ExpenseCategory, User
from app.middleware.auth import require_admin
from app.cache import cache_get, cache_set

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

@router.get("/kpis")
async def get_dashboard_kpis(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Top-level KPI cards for admin dashboard"""
    cache_key = "dashboard:kpis"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    total_hubs = await db.execute(select(func.count(Hub.id)).where(Hub.is_active == True))
    total_hubs = total_hubs.scalar()

    total_ytd = await db.execute(select(func.sum(HubAggregate.total_amount)))
    total_ytd = total_ytd.scalar() or 0

    flagged_hubs = await db.execute(
        select(HubAggregate.hub_id)
        .group_by(HubAggregate.hub_id)
        .having(func.sum(HubAggregate.total_amount) > 200000)
    )
    flagged_count = len(flagged_hubs.all())

    top_hub = await db.execute(
        select(Hub.hub_code, func.sum(HubAggregate.total_amount).label("ytd"))
        .join(HubAggregate, Hub.id == HubAggregate.hub_id)
        .group_by(Hub.hub_code)
        .order_by(func.sum(HubAggregate.total_amount).desc())
        .limit(1)
    )
    top_hub_row = top_hub.first()

    result = {
        "total_hubs": total_hubs,
        "total_ytd": round(total_ytd, 2),
        "flagged_hubs": flagged_count,
        "top_hub": {"code": top_hub_row[0], "ytd": round(top_hub_row[1], 2)} if top_hub_row else None,
    }

    await cache_set(cache_key, result, ttl=3600)
    return result


@router.get("/state-spend")
async def get_state_spend(
    year: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """YTD spend grouped by state"""
    cache_key = f"dashboard:state_spend:{year}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    query = (
        select(Hub.state, func.sum(HubAggregate.total_amount).label("total"))
        .join(HubAggregate, Hub.id == HubAggregate.hub_id)
    )
    if year:
        query = query.where(HubAggregate.year == year)
    query = query.group_by(Hub.state).order_by(func.sum(HubAggregate.total_amount).desc())

    result = await db.execute(query)
    rows = result.all()
    out = [{"state": r.state, "value": round(r.total or 0, 2)} for r in rows if r.state]

    await cache_set(cache_key, out, ttl=3600)
    return out


@router.get("/category-mix")
async def get_category_mix(
    year: Optional[int] = Query(None),
    state: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """National category-wise split for pie chart"""
    cache_key = f"dashboard:category_mix:{year}:{state}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    query = (
        select(ExpenseCategory.display_name, func.sum(HubAggregate.total_amount).label("total"))
        .join(HubAggregate, ExpenseCategory.id == HubAggregate.category_id)
    )
    if year:
        query = query.where(HubAggregate.year == year)
    if state:
        query = (
            query
            .join(Hub, Hub.id == HubAggregate.hub_id)
            .where(Hub.state == state)
        )
    query = query.group_by(ExpenseCategory.display_name).order_by(func.sum(HubAggregate.total_amount).desc())

    result = await db.execute(query)
    rows = result.all()
    out = [{"name": r.display_name, "value": round(r.total or 0, 2)} for r in rows]

    await cache_set(cache_key, out, ttl=3600)
    return out


@router.get("/top-hubs")
async def get_top_hubs(
    limit: int = Query(10, ge=1, le=50),
    year: Optional[int] = Query(None),
    state: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Top hubs by spend — leaderboard"""
    query = (
        select(
            Hub.hub_code, Hub.city, Hub.state, Hub.tier,
            func.sum(HubAggregate.total_amount).label("ytd")
        )
        .join(HubAggregate, Hub.id == HubAggregate.hub_id)
    )
    if year:
        query = query.where(HubAggregate.year == year)
    if state:
        query = query.where(Hub.state == state)

    query = (
        query
        .group_by(Hub.hub_code, Hub.city, Hub.state, Hub.tier)
        .order_by(func.sum(HubAggregate.total_amount).desc())
        .limit(limit)
    )
    result = await db.execute(query)
    rows = result.all()
    return [
        {"rank": i + 1, "hub_code": r.hub_code, "city": r.city,
         "state": r.state, "tier": r.tier, "ytd": round(r.ytd or 0, 2)}
        for i, r in enumerate(rows)
    ]


@router.get("/flagged-hubs")
async def get_flagged_hubs(
    threshold: float = Query(200000, description="Flag hubs with YTD above this amount"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Hubs above spend threshold — audit view"""
    query = (
        select(
            Hub.hub_code, Hub.city, Hub.state, Hub.tier, Hub.manager_name,
            func.sum(HubAggregate.total_amount).label("ytd"),
            func.sum(HubAggregate.policy_violation_count).label("violations")
        )
        .join(HubAggregate, Hub.id == HubAggregate.hub_id)
        .group_by(Hub.hub_code, Hub.city, Hub.state, Hub.tier, Hub.manager_name)
        .having(func.sum(HubAggregate.total_amount) > threshold)
        .order_by(func.sum(HubAggregate.total_amount).desc())
    )
    result = await db.execute(query)
    rows = result.all()
    return [
        {
            "hub_code": r.hub_code, "city": r.city, "state": r.state,
            "tier": r.tier, "manager": r.manager_name,
            "ytd": round(r.ytd or 0, 2), "violations": r.violations or 0,
            "status": "Flagged"
        }
        for r in rows
    ]
