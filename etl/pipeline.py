"""
ETL Pipeline — Hub Portal
Reads the 200MB Excel from Google Drive, normalises columns,
maps category chains, and upserts into PostgreSQL.
Runs nightly at 2AM IST + on-demand via API.
"""
import pandas as pd
import io
import json
import logging
from datetime import datetime, date
from typing import Optional
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("etl")

# ── Category chain → standard display name mapping ────────────────────────────
CATEGORY_MAP = {
    # Housekeeping
    "House Keeping":                    "Housekeeping",
    "Housekeeping":                     "Housekeeping",
    "Staff Welfare (Other than Food/Tea/Coffee/Water)": "Housekeeping",

    # Tea / Coffee / Water
    "Tea/Coffee/Water":                 "Tea / Coffee / Water",
    "Tea Coffee Water":                 "Tea / Coffee / Water",

    # Printing & Stationery
    "Printing & Stationary":            "Printing & Stationery",
    "Printing & Stationery":            "Printing & Stationery",
    "Courier charges":                  "Printing & Stationery",

    # Repair & Maintenance
    "Repairs & Maintainance":           "Repair & Maintenance",
    "Repair & Maintenance":             "Repair & Maintenance",

    # Electricity
    "Electricity":                      "Electricity",

    # Internet & Mobile
    "Internet":                         "Internet & Mobile",
    "Mobile Reimbursement":             "Internet & Mobile",
    "Transactional SMS":                "Internet & Mobile",

    # Rent
    "Rent - Maintenance":               "Rent",
    "Rent":                             "Rent",
    "Rates & Taxes":                    "Rent",

    # Miscellaneous (not shown as main category but stored)
    "Miscellaneous Expenses":           "Miscellaneous",
    "Professional Fees":                "Miscellaneous",
    "Food":                             "Food & Welfare",
    "Food - Staff Welfare--With Bills": "Food & Welfare",
    "Food--Without Bill":               "Food & Welfare",
    "Food and Miscellaneous":           "Food & Welfare",
    "Rider Meet Expenses":              "Food & Welfare",
    "Team Building":                    "Food & Welfare",
    "Marketing Expenses":               "Miscellaneous",
    "Local Transport":                  "Travel & Transport",
    "Conveyance":                       "Travel & Transport",
    "Public Transport":                 "Travel & Transport",
    "Accomodation - With Bill":         "Travel & Transport",
    "Third Party Rider Cost":           "Operations",
    "3PL & Franchisee":                 "Operations",
    "Adhoc Rider Payment":              "Operations",
    "Transportation - Adhoc Vehicles--Transportation - Adhoc Vehicles": "Operations",
}

FACILITY_EXPENSE_CATEGORIES = {
    "Housekeeping", "Tea / Coffee / Water", "Printing & Stationery",
    "Repair & Maintenance", "Electricity", "Internet & Mobile", "Rent"
}


def download_from_google_drive(file_id: str) -> bytes:
    """Download file from Google Drive using service account"""
    import json
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload

    sa_info = json.loads(settings.GOOGLE_SERVICE_ACCOUNT_JSON)
    creds = service_account.Credentials.from_service_account_info(
        sa_info,
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    service = build("drive", "v3", credentials=creds)

    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
        log.info("Download progress...")

    return buffer.getvalue()


def read_excel(data: bytes) -> pd.DataFrame:
    log.info("Reading Excel file...")
    df = pd.read_excel(io.BytesIO(data), engine="openpyxl")
    log.info(f"Loaded {len(df)} rows, {len(df.columns)} columns")
    return df


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    log.info("Cleaning dataframe...")

    # Normalise column names
    df.columns = [str(c).strip() for c in df.columns]

    # Parse expense date
    if "Date of expense" in df.columns:
        df["_expense_date"] = pd.to_datetime(df["Date of expense"], errors="coerce", dayfirst=True)
    elif "Date" in df.columns:
        df["_expense_date"] = pd.to_datetime(df["Date"], errors="coerce", dayfirst=True)

    # Core fields
    df["_hub_code"]      = df.get("Sitting Location", pd.Series()).fillna("").str.strip()
    df["_city"]          = df.get("City", pd.Series()).fillna("").str.strip()
    df["_state"]         = df.get("State", pd.Series()).fillna("").str.strip()
    df["_category_raw"]  = df.get("Category chain", pd.Series()).fillna("").str.strip()
    df["_expense_type"]  = df.get("Expense Type", pd.Series()).fillna("").str.strip()
    df["_amount"]        = pd.to_numeric(df.get("Expense Amount", pd.Series()), errors="coerce").fillna(0)
    df["_approved"]      = pd.to_numeric(df.get("Approved amount", pd.Series()), errors="coerce").fillna(0)
    df["_status"]        = df.get("Transaction Status", pd.Series()).fillna("").str.strip()
    df["_employee"]      = df.get("Name", pd.Series()).fillna("").str.strip()
    df["_employee_id"]   = df.get("Employee_Id", pd.Series()).fillna("").str.strip()
    df["_role"]          = df.get("Role", pd.Series()).fillna("").str.strip()
    df["_band"]          = df.get("BAND", pd.Series()).fillna("").str.strip()
    df["_facility_type"] = df.get("Facility Type", pd.Series()).fillna("").str.strip()
    df["_tier"]          = df.get("Tier", pd.Series()).fillna("").str.strip()
    df["_site_category"] = df.get("Site Category", pd.Series()).fillna("").str.strip()
    df["_cost_centre"]   = df.get("Cost Centre", pd.Series()).fillna("").str.strip()
    df["_sub_cost_centre"] = df.get("Sub Cost Center", pd.Series()).fillna("").str.strip()
    df["_description"]   = df.get("Description", pd.Series()).fillna("").str.strip()
    df["_policy_violation"] = df.get("Policy Violation", pd.Series()).fillna("No").str.strip().str.lower() == "yes"
    df["_report_id"]     = df.get("Report ID", pd.Series()).fillna("").str.strip()
    df["_report_name"]   = df.get("Report name", pd.Series()).fillna("").str.strip()
    df["_vendor"]        = df.get("Vendor Name", pd.Series()).fillna("").str.strip()
    df["_attachment"]    = df.get("Attachments", pd.Series()).fillna("").str.strip()
    df["_bill_available"] = df.get("Bill Available", pd.Series()).fillna("").str.strip()

    # Map category
    df["_category_display"] = df["_category_raw"].map(CATEGORY_MAP).fillna("Other")

    # Filter to Hub facility type only (main use case)
    # You can remove this filter to include all facility types
    # df = df[df["_facility_type"] == "Hub"]

    # Remove rows without hub code
    df = df[df["_hub_code"].str.len() > 0]

    log.info(f"After cleaning: {len(df)} rows")
    return df


def upsert_to_db(df: pd.DataFrame, log_id: str):
    """Upsert hubs, categories, expenses and rebuild aggregates"""
    engine = create_engine(settings.SYNC_DATABASE_URL)

    with Session(engine) as session:
        # ── 1. Upsert hubs ─────────────────────────────────────────────────────
        log.info("Upserting hubs...")
        hub_cols = ["_hub_code","_city","_state","_facility_type","_tier","_site_category","_cost_centre","_sub_cost_centre"]
        hub_df = df[hub_cols].drop_duplicates(subset=["_hub_code"])

        for _, row in hub_df.iterrows():
            session.execute(text("""
                INSERT INTO hubs (id, hub_code, sitting_location, city, state, facility_type,
                                  tier, site_category, cost_centre, sub_cost_centre)
                VALUES (gen_random_uuid(), :hub_code, :hub_code, :city, :state, :facility_type,
                        :tier, :site_category, :cost_centre, :sub_cost_centre)
                ON CONFLICT (hub_code) DO UPDATE SET
                    city = EXCLUDED.city,
                    state = EXCLUDED.state,
                    facility_type = EXCLUDED.facility_type,
                    tier = EXCLUDED.tier,
                    site_category = EXCLUDED.site_category,
                    cost_centre = EXCLUDED.cost_centre,
                    sub_cost_centre = EXCLUDED.sub_cost_centre,
                    updated_at = now()
            """), {
                "hub_code": row["_hub_code"],
                "city": row["_city"] or None,
                "state": row["_state"] or None,
                "facility_type": row["_facility_type"] or None,
                "tier": row["_tier"] or None,
                "site_category": row["_site_category"] or None,
                "cost_centre": row["_cost_centre"] or None,
                "sub_cost_centre": row["_sub_cost_centre"] or None,
            })
        session.commit()
        log.info(f"Upserted {len(hub_df)} hubs")

        # ── 2. Upsert expense categories ──────────────────────────────────────
        categories = df["_category_display"].unique()
        for cat in categories:
            raw_chains = ", ".join(df[df["_category_display"] == cat]["_category_raw"].unique()[:20])
            session.execute(text("""
                INSERT INTO expense_categories (id, category_key, display_name, raw_chains)
                VALUES (gen_random_uuid(), :key, :name, :chains)
                ON CONFLICT (category_key) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    raw_chains = EXCLUDED.raw_chains
            """), {"key": cat, "name": cat, "chains": raw_chains})
        session.commit()

        # ── 3. Build hub_id and category_id lookup maps ───────────────────────
        hub_ids = {r[0]: r[1] for r in session.execute(text("SELECT hub_code, id FROM hubs")).all()}
        cat_ids = {r[0]: r[1] for r in session.execute(text("SELECT category_key, id FROM expense_categories")).all()}

        # ── 4. Insert expenses in batches ─────────────────────────────────────
        log.info("Inserting expenses...")
        batch_size = 1000
        total_inserted = 0

        for i in range(0, len(df), batch_size):
            batch = df.iloc[i:i+batch_size]
            rows = []
            for _, row in batch.iterrows():
                hub_id = hub_ids.get(row["_hub_code"])
                cat_id = cat_ids.get(row["_category_display"])
                if not hub_id:
                    continue
                exp_date = row["_expense_date"].date() if pd.notna(row.get("_expense_date")) else None
                rows.append({
                    "hub_id": str(hub_id),
                    "category_id": str(cat_id) if cat_id else None,
                    "raw_category_chain": row["_category_raw"],
                    "employee_name": row["_employee"] or None,
                    "employee_id": row["_employee_id"] or None,
                    "role": row["_role"] or None,
                    "band": row["_band"] or None,
                    "expense_date": exp_date,
                    "expense_amount": float(row["_amount"]),
                    "approved_amount": float(row["_approved"]),
                    "transaction_status": row["_status"] or None,
                    "report_id": row["_report_id"] or None,
                    "report_name": row["_report_name"] or None,
                    "description": row["_description"] or None,
                    "policy_violation": bool(row["_policy_violation"]),
                    "vendor_name": row["_vendor"] or None,
                    "attachment_url": row["_attachment"] or None,
                })
            if rows:
                session.execute(text("""
                    INSERT INTO expenses (id, hub_id, category_id, raw_category_chain,
                        employee_name, employee_id, role, band, expense_date,
                        expense_amount, approved_amount, transaction_status,
                        report_id, report_name, description, policy_violation,
                        vendor_name, attachment_url)
                    VALUES (gen_random_uuid(), :hub_id, :category_id, :raw_category_chain,
                        :employee_name, :employee_id, :role, :band, :expense_date,
                        :expense_amount, :approved_amount, :transaction_status,
                        :report_id, :report_name, :description, :policy_violation,
                        :vendor_name, :attachment_url)
                """), rows)
                session.commit()
                total_inserted += len(rows)
                log.info(f"Inserted batch {i//batch_size + 1}: {total_inserted} rows so far")

        # ── 5. Rebuild monthly aggregates ─────────────────────────────────────
        log.info("Rebuilding aggregates...")
        session.execute(text("DELETE FROM hub_aggregates"))
        session.execute(text("""
            INSERT INTO hub_aggregates (id, hub_id, category_id, month, year,
                total_amount, approved_amount, transaction_count, policy_violation_count)
            SELECT
                gen_random_uuid(),
                hub_id,
                category_id,
                EXTRACT(MONTH FROM expense_date)::int,
                EXTRACT(YEAR FROM expense_date)::int,
                SUM(expense_amount),
                SUM(approved_amount),
                COUNT(*),
                SUM(CASE WHEN policy_violation THEN 1 ELSE 0 END)
            FROM expenses
            WHERE expense_date IS NOT NULL
            GROUP BY hub_id, category_id,
                EXTRACT(MONTH FROM expense_date),
                EXTRACT(YEAR FROM expense_date)
        """))
        session.commit()
        log.info("Aggregates rebuilt")

        # ── 6. Update ETL log ─────────────────────────────────────────────────
        session.execute(text("""
            UPDATE etl_logs SET
                finished_at = now(),
                status = 'success',
                rows_processed = :processed,
                rows_inserted = :inserted
            WHERE id = :log_id
        """), {"processed": len(df), "inserted": total_inserted, "log_id": log_id})
        session.commit()

    return total_inserted


def run_etl(triggered_by: str = "scheduler"):
    """Main ETL entry point"""
    log.info(f"ETL started — triggered by: {triggered_by}")
    engine = create_engine(settings.SYNC_DATABASE_URL)

    # Create log entry
    with Session(engine) as session:
        result = session.execute(text("""
            INSERT INTO etl_logs (id, status, triggered_by)
            VALUES (gen_random_uuid(), 'running', :triggered_by)
            RETURNING id
        """), {"triggered_by": triggered_by})
        log_id = str(result.scalar())
        session.commit()

    try:
        file_bytes = download_from_google_drive(settings.GOOGLE_DRIVE_FILE_ID)
        df = read_excel(file_bytes)
        df = clean_dataframe(df)
        inserted = upsert_to_db(df, log_id)
        log.info(f"ETL complete — {inserted} rows inserted")
    except Exception as e:
        log.error(f"ETL failed: {e}")
        with Session(engine) as session:
            session.execute(text("""
                UPDATE etl_logs SET
                    finished_at = now(), status = 'failed', error_message = :err
                WHERE id = :log_id
            """), {"err": str(e), "log_id": log_id})
            session.commit()
        raise
