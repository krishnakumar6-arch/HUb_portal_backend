from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator
from app.database import get_db
from app.models.models import User
from app.middleware.auth import verify_password, create_token, get_current_user, hash_password, require_admin

router = APIRouter(prefix="/auth", tags=["auth"])

# ── Allowed email domain ───────────────────────────────────────────────────────
ALLOWED_DOMAIN = "shadowfax.in"

def validate_domain(email: str):
    """Raises 403 if email is not from the allowed domain"""
    domain = email.strip().lower().split("@")[-1]
    if domain != ALLOWED_DOMAIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied. Only @{ALLOWED_DOMAIN} email addresses are permitted on this portal."
        )

# ── Request / Response models ──────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def email_must_be_shadowfax(cls, v):
        domain = str(v).strip().lower().split("@")[-1]
        if domain != ALLOWED_DOMAIN:
            raise ValueError(f"Only @{ALLOWED_DOMAIN} email addresses are permitted")
        return str(v).strip().lower()

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict

class CreateUserRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "hi"         # "admin" | "hi"
    department: str = ""
    hub_code: str = ""       # required if role == "hi"

    @field_validator("email")
    @classmethod
    def email_must_be_shadowfax(cls, v):
        domain = str(v).strip().lower().split("@")[-1]
        if domain != ALLOWED_DOMAIN:
            raise ValueError(f"Only @{ALLOWED_DOMAIN} email addresses are allowed")
        return str(v).strip().lower()

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v):
        if v not in ("admin", "hi"):
            raise ValueError("Role must be 'admin' or 'hi'")
        return v

# ── LOGIN ──────────────────────────────────────────────────────────────────────
@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Login with @shadowfax.in email only.
    Returns JWT token with role and hub_id encoded.
    """
    email = body.email.strip().lower()

    # Step 1: domain check (also validated in pydantic but double-checked here)
    validate_domain(email)

    # Step 2: look up user in database
    result = await db.execute(
        select(User).where(User.email == email, User.is_active == True)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account not found. Contact your admin to create an account for you."
        )

    # Step 3: verify password
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password. Please try again."
        )

    # Step 4: update last login
    user.last_login = datetime.utcnow()
    await db.commit()

    # Step 5: issue JWT with role + hub_id encoded
    token = create_token({
        "sub": user.email,
        "role": user.role,
        "hub_id": str(user.hub_id) if user.hub_id else None,
        "name": user.name,
    })

    return {
        "access_token": token,
        "user": {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "department": user.department,
            "hub_id": str(user.hub_id) if user.hub_id else None,
        }
    }

# ── CREATE USER (admin only) ───────────────────────────────────────────────────
@router.post("/users", status_code=201)
async def create_user(
    body: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """
    Admin creates a new user account.
    Only @shadowfax.in emails accepted.
    HI users must be linked to a hub_code.
    """
    email = body.email.strip().lower()

    # Ensure no duplicate
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"An account for {email} already exists.")

    # Resolve hub_id for HI users
    hub_id = None
    if body.role == "hi":
        if not body.hub_code:
            raise HTTPException(status_code=400, detail="Hub Incharge users must be assigned a hub_code.")
        from app.models.models import Hub
        hub_result = await db.execute(select(Hub).where(Hub.hub_code == body.hub_code))
        hub = hub_result.scalar_one_or_none()
        if not hub:
            raise HTTPException(status_code=404, detail=f"Hub '{body.hub_code}' not found in database.")
        hub_id = hub.id

    user = User(
        name=body.name,
        email=email,
        hashed_password=hash_password(body.password),
        role=body.role,
        department=body.department,
        hub_id=hub_id,
    )
    db.add(user)
    await db.commit()

    return {
        "message": f"Account created for {email}",
        "email": email,
        "role": body.role,
        "hub_code": body.hub_code or None,
    }

# ── LIST USERS (admin only) ────────────────────────────────────────────────────
@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """List all users — admin only"""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [
        {
            "id": str(u.id),
            "name": u.name,
            "email": u.email,
            "role": u.role,
            "department": u.department,
            "hub_id": str(u.hub_id) if u.hub_id else None,
            "is_active": u.is_active,
            "last_login": str(u.last_login) if u.last_login else None,
        }
        for u in users
    ]

# ── DEACTIVATE USER (admin only) ──────────────────────────────────────────────
@router.patch("/users/{email}/deactivate")
async def deactivate_user(
    email: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Revoke access for a user without deleting their data"""
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    await db.commit()
    return {"message": f"Access revoked for {email}"}

# ── ME ─────────────────────────────────────────────────────────────────────────
@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role,
        "department": current_user.department,
        "hub_id": str(current_user.hub_id) if current_user.hub_id else None,
    }
