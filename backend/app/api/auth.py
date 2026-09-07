"""Auth API: login and default admin bootstrap."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import (
    verify_password, create_access_token, hash_password, get_current_user,
)
from app.models import User
from app.schemas.schemas import Token, LoginRequest, ChangePasswordRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=Token)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_access_token(user.username)
    return Token(access_token=token)


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {"username": user.username, "role": user.role}


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(req.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="原密码错误")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少6位")
    user.hashed_password = hash_password(req.new_password)
    await db.commit()
    return {"ok": True}


async def ensure_admin_user(db: AsyncSession):
    """Create default admin/admin account if no user exists."""
    result = await db.execute(select(User).limit(1))
    if result.scalar_one_or_none() is None:
        db.add(User(
            username="admin",
            hashed_password=hash_password("admin123"),
            role="admin",
        ))
        await db.commit()
