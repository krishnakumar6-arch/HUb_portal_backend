from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from pydantic import BaseModel, EmailStr
from app.database import get_db
from app.models.models import User
from app.middleware.auth import verify_password, create_token, get_current_user, hash_password, require_admin

router = APIRouter(prefix="/auth", tags=["auth"])

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict

class CreateUserRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "hi"        # "admin" | "hi"
    department: str = ""
    hub_code: str = ""      # required if role == "hi"

@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(User.email == body.email, User.is_active == True)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )

    # Update last login
    user.last_login = datetime.utcnow()
    await db.commit()

    token = create_token({
        "sub": user.email,
        "role": user.role,
        "hub_id": str(user.hub_id) if user.hub_id else None,
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

@router.post("/users", status_code=201)
async def create_user(
    body: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Admin only — create new user"""
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    hub_id = None
    if body.role == "hi" and body.hub_code:
        from app.models.models import Hub
        hub_result = await db.execute(select(Hub).where(Hub.hub_code == body.hub_code))
        hub = hub_result.scalar_one_or_none()
        if not hub:
            raise HTTPException(status_code=404, detail=f"Hub '{body.hub_code}' not found")
        hub_id = hub.id

    user = User(
        name=body.name,
        email=body.email,
        hashed_password=hash_password(body.password),
        role=body.role,
        department=body.department,
        hub_id=hub_id,
    )
    db.add(user)
    await db.commit()
    return {"message": "User created", "email": user.email, "role": user.role}

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
