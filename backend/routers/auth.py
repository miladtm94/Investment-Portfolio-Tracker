"""Authentication router — register, login, profile."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from shared.models import User
from shared.auth import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None
    preferred_currency: str = "USD"
    timezone: str = "UTC"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str | None
    preferred_currency: str
    timezone: str
    cost_basis_method: str
    created_at: datetime

    class Config:
        from_attributes = True


class UpdateProfileRequest(BaseModel):
    full_name: str | None = None
    preferred_currency: str | None = None
    timezone: str | None = None
    cost_basis_method: str | None = None


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Check if email already exists
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        preferred_currency=body.preferred_currency,
        timezone=body.timezone,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id, user.email)
    return TokenResponse(access_token=token, user_id=user.id, email=user.email)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email, User.is_active == True))
    user = result.scalar_one_or_none()

    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(user.id, user.email)
    return TokenResponse(access_token=token, user_id=user.id, email=user.email)


@router.get("/me", response_model=UserResponse)
async def get_profile(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=UserResponse)
async def update_profile(
    body: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.full_name is not None:
        current_user.full_name = body.full_name
    if body.preferred_currency is not None:
        current_user.preferred_currency = body.preferred_currency.upper()
    if body.timezone is not None:
        current_user.timezone = body.timezone
    if body.cost_basis_method is not None:
        if body.cost_basis_method not in ("FIFO", "LIFO", "HIFO"):
            raise HTTPException(status_code=400, detail="Invalid cost basis method")
        current_user.cost_basis_method = body.cost_basis_method

    current_user.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(current_user)
    return current_user
