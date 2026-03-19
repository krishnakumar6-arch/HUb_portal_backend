from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from typing import Optional, List
from app.database import get_db
from app.models.models import Hub, HubAggregate, HubSqft, User
from app.middleware.auth import get_current_user
from app.cache import cache_get, cache_set
import json

router = APIRouter(prefix="/hubs", tags=["hubs"])

def _hub_to_dict(hub: Hub) -> dict:
    return {
        "id": str(hub.id),
        "hub_code": hub.hub_code,
        "hub_name": hub.hub_name or hub.hub_code,
        "city": hub.city,
        "state": hub.state,
        "tier": hub.tier,
        "facility_type": hub.facility_type,
        "site_category": hub.site_category,
        "cost_centre": hub.cost_centre,
        "manager_name": hub.manager_name,
        "is_active": hub.is_active,
    }

@router.get("")
async def search_hubs(
    q: Optional[str] = Query(None, description="Hub code, city, or state"),
    state: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    tier: Optional[str] = Query(None),
    facility_type: Optional[str] = Query(None),
    sort: str = Query("spend", description="spend | name"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Search hubs. HI users can only see their own hub."""

    # HI users: only their hub
    if current_user.role == "hi":
        if not current_user.hub_id:
            return {"hubs": [], "total": 0}
        result = await db.execute(select(Hub).where(Hub.id == current_user.hub_id))
        hub = result.scalar_one_or_none()
        return {"hubs": [_hub_to_dict(hub)] if hub else [], "total": 1}

    # Admin: full search
    query = select(Hub).where(Hub.is_active == True)

    if q:
        query = query.where(or_(
            Hub.hub_code.ilike(f"%{q}%"),
            Hub.city.ilike(f"%{q}%"),
            Hub.state.ilike(f"%{q}%"),
            Hub.hub_name.ilike(f"%{q}%"),
        ))
    if state:
        query = query.where(Hub.state == state)
    if city:
        query = query.where(Hub.city == city)
    if tier:
        query = query.where(Hub.tier == tier)
    if facility_type:
        query = query.where(Hub.facility_type == facility_type)

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar()

    if sort == "name":
        query = query.order_by(Hub.hub_code)
    else:
        query = query.order_by(Hub.hub_code)  # default; spend sort added after aggregate join below

    query = query.offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    hubs = result.scalars().all()

    # Attach YTD spend to each hub
    hub_ids = [h.id for h in hubs]
    if hub_ids:
        agg_result = await db.execute(
            select(HubAggregate.hub_id, func.sum(HubAggregate.total_amount).label("ytd"))
            .where(HubAggregate.hub_id.in_(hub_ids))
            .group_by(HubAggregate.hub_id)
        )
        ytd_map = {str(r.hub_id): r.ytd or 0 for r in agg_result.all()}
    else:
        ytd_map = {}

    hubs_out = []
    for h in hubs:
        d = _hub_to_dict(h)
        d["total_ytd"] = ytd_map.get(str(h.id), 0)
        hubs_out.append(d)

    if sort == "spend":
        hubs_out.sort(key=lambda x: x["total_ytd"], reverse=True)

    return {"hubs": hubs_out, "total": total, "page": page, "limit": limit}


@router.get("/filters")
async def get_filter_options(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get distinct states, cities, tiers for filter dropdowns"""
    cache_key = "filters:options"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    states = await db.execute(select(Hub.state).distinct().where(Hub.state.isnot(None)).order_by(Hub.state))
    cities = await db.execute(select(Hub.city).distinct().where(Hub.city.isnot(None)).order_by(Hub.city))
    tiers  = await db.execute(select(Hub.tier).distinct().where(Hub.tier.isnot(None)).order_by(Hub.tier))

    result = {
        "states": [r[0] for r in states.all()],
        "cities": [r[0] for r in cities.all()],
        "tiers":  [r[0] for r in tiers.all()],
    }
    await cache_set(cache_key, result, ttl=86400)
    return result


@router.get("/{hub_code}")
async def get_hub_detail(
    hub_code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get full hub detail including monthly aggregates. HI enforced server-side."""
    cache_key = f"hub:detail:{hub_code}"
    cached = await cache_get(cache_key)
    if cached:
        # Role check even on cache
        if current_user.role == "hi":
            if cached.get("hub_code") != hub_code or str(current_user.hub_id) != cached.get("id"):
                raise HTTPException(status_code=403, detail="Access denied")
        return cached

    result = await db.execute(select(Hub).where(Hub.hub_code == hub_code))
    hub = result.scalar_one_or_none()
    if not hub:
        raise HTTPException(status_code=404, detail="Hub not found")

    # Role enforcement
    if current_user.role == "hi" and hub.id != current_user.hub_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Monthly aggregates (all categories, all months/years)
    agg_result = await db.execute(
        select(HubAggregate)
        .where(HubAggregate.hub_id == hub.id)
        .order_by(HubAggregate.year, HubAggregate.month)
    )
    aggregates = agg_result.scalars().all()

    # Sqft
    sqft_result = await db.execute(select(HubSqft).where(HubSqft.hub_id == hub.id))
    sqft_row = sqft_result.scalar_one_or_none()

    monthly_map: dict = {}
    for agg in aggregates:
        key = f"{agg.year}-{agg.month:02d}"
        if key not in monthly_map:
            monthly_map[key] = {"year": agg.year, "month": agg.month, "categories": {}, "total": 0}
        # category_id mapped to display name done in service layer
        monthly_map[key]["categories"][str(agg.category_id)] = agg.total_amount
        monthly_map[key]["total"] += (agg.total_amount or 0)

    total_ytd = sum(v["total"] for v in monthly_map.values())

    out = {
        **_hub_to_dict(hub),
        "sqft": sqft_row.sqft_area if sqft_row else None,
        "total_ytd": total_ytd,
        "monthly_data": list(monthly_map.values()),
    }

    await cache_set(cache_key, out, ttl=3600)
    return out


@router.get("/{hub_code}/expenses")
async def get_hub_expenses(
    hub_code: str,
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Raw expense transactions for a hub"""
    from app.models.models import Expense, ExpenseCategory
    from sqlalchemy import extract

    hub_result = await db.execute(select(Hub).where(Hub.hub_code == hub_code))
    hub = hub_result.scalar_one_or_none()
    if not hub:
        raise HTTPException(status_code=404, detail="Hub not found")

    if current_user.role == "hi" and hub.id != current_user.hub_id:
        raise HTTPException(status_code=403, detail="Access denied")

    query = select(Expense).where(Expense.hub_id == hub.id)
    if month:
        query = query.where(extract("month", Expense.expense_date) == month)
    if year:
        query = query.where(extract("year", Expense.expense_date) == year)
    if category:
        cat_res = await db.execute(select(ExpenseCategory).where(ExpenseCategory.category_key == category))
        cat = cat_res.scalar_one_or_none()
        if cat:
            query = query.where(Expense.category_id == cat.id)
    if status:
        query = query.where(Expense.transaction_status == status)

    total_res = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_res.scalar()

    query = query.order_by(Expense.expense_date.desc()).offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    expenses = result.scalars().all()

    return {
        "expenses": [
            {
                "id": str(e.id),
                "date": str(e.expense_date),
                "category": e.raw_category_chain,
                "employee": e.employee_name,
                "amount": e.expense_amount,
                "approved_amount": e.approved_amount,
                "status": e.transaction_status,
                "description": e.description,
                "policy_violation": e.policy_violation,
                "vendor": e.vendor_name,
            }
            for e in expenses
        ],
        "total": total,
        "page": page,
        "limit": limit
    }
