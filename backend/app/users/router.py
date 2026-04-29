"""/api/users/me endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.security import hash_password, verify_password
from app.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.auth import UserOut
from app.schemas.user import ChangePasswordIn, UpdateMeIn


router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=UserOut)
def get_me(current: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current)


@router.patch("/me", response_model=UserOut)
def update_me(
    payload: UpdateMeIn,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserOut:
    current.phone = payload.phone
    db.commit()
    db.refresh(current)
    return UserOut.model_validate(current)


@router.post("/me/change-password", status_code=status.HTTP_200_OK)
def change_password(
    payload: ChangePasswordIn,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not verify_password(payload.old_password, current.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "AUTH_INVALID", "message": "旧密码错误"}},
        )
    current.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"ok": True}
