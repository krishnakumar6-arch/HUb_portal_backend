from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, extract
from typing import Optional
import csv, io
from app.database import get_db
from app.models.models import Hub, Expense, HubAggregate, User
from app.middleware.auth import get_current_user

router = APIRouter(prefix="/export", tags=["export"])

@router.get("/hub/{hub_code}/csv")
async def export_hub_csv(
    hub_code: str,
    month: Optional[int] = Query(None),
    year: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Download hub expenses as CSV"""
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
    query = query.order_by(Expense.expense_date.desc())

    result = await db.execute(query)
    expenses = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Date", "Hub Code", "Employee", "Category", "Description",
        "Amount (INR)", "Approved Amount", "Status", "Policy Violation", "Vendor"
    ])
    for e in expenses:
        writer.writerow([
            e.expense_date, hub.hub_code, e.employee_name,
            e.raw_category_chain, e.description,
            e.expense_amount, e.approved_amount,
            e.transaction_status, "Yes" if e.policy_violation else "No",
            e.vendor_name or ""
        ])

    output.seek(0)
    filename = f"{hub_code}_expenses"
    if year:
        filename += f"_{year}"
    if month:
        filename += f"_{month:02d}"
    filename += ".csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
