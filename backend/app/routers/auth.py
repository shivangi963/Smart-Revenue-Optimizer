"""Login, session info, password change and (admin) user management."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import User
from ..schemas import ChangePassword, UserCreate, UserOut, UserUpdate
from ..security import (
    DEFAULT_ADMIN_PASSWORD, create_token, dummy_verify, get_current_user, hash_password, login_throttle,
    require_admin, verify_password,
)
from ..utils.timeutils import utcnow
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["Authentication"])

class RegisterRequest(BaseModel):
    username: str
    password: str


def _session(user: User) -> dict:
    return {"access_token": create_token(user), "token_type": "bearer",
            "expires_in": settings.token_expire_minutes * 60,
            "user": UserOut.model_validate(user).model_dump(mode="json")}


@router.get("/status")
def auth_status(db: Session = Depends(get_db)):
    """Public. Lets the login page know whether to show the demo-credentials hint."""
    if not settings.auth_enabled:
        return {"auth_enabled": False, "default_credentials": False}
    default_admin = (db.query(User).filter(User.role == "admin", User.is_active.is_(True),
                                           User.must_change_password.is_(True)).first())
    return {"auth_enabled": True, "default_credentials": bool(default_admin),
            "hint_username": default_admin.username if default_admin else None,
            "hint_password": DEFAULT_ADMIN_PASSWORD if default_admin else None}


@router.post("/login")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    if not settings.auth_enabled:
        raise HTTPException(400, "Authentication is disabled on this server.")
    key = f"{form.username.lower()}|{request.client.host if request.client else '?'}"
    wait = login_throttle.retry_after(key)
    if wait:
        raise HTTPException(429, f"Too many failed attempts. Try again in {wait} seconds.",
                            headers={"Retry-After": str(wait)})
    user = db.query(User).filter(func.lower(User.username) == form.username.lower()).first()
    if user is None:
        dummy_verify(form.password)
        ok = False
    else:
        ok = verify_password(form.password, user.password_hash) and bool(user.is_active)
    if not ok:
        login_throttle.record_failure(key)
        raise HTTPException(401, "Incorrect username or password.", headers={"WWW-Authenticate": "Bearer"})
    login_throttle.clear(key)
    user.last_login = utcnow()
    db.commit()
    return _session(user)


@router.get("/me", response_model=UserOut)
def me(user=Depends(get_current_user)):
    return user


@router.post("/change-password")
def change_password(body: ChangePassword, user=Depends(get_current_user), db: Session = Depends(get_db)):
    if not settings.auth_enabled:
        raise HTTPException(400, "Authentication is disabled on this server.")
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Your current password is incorrect.")
    if body.current_password == body.new_password:
        raise HTTPException(400, "Choose a password different from the current one.")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.token_version = (user.token_version or 0) + 1        # signs out every other device
    db.commit()
    return _session(user)                                      # fresh token so *this* session continues



# ------------------------------------------------------------ public registration

@router.post("/register", response_model=UserOut, status_code=201)
def register_user(body: RegisterRequest, db: Session = Depends(get_db)):
    """Public registration. Every new account receives the viewer role."""

    if not settings.auth_enabled:
        raise HTTPException(400, "Registration is disabled on this server.")

    # Reuse existing username/password validation rules.
    validated = UserCreate(
        username=body.username,
        password=body.password,
        role="viewer"
    )

    # Prevent duplicate usernames, ignoring uppercase/lowercase differences.
    existing = db.query(User).filter(
        func.lower(User.username) == validated.username.lower()
    ).first()

    if existing:
        raise HTTPException(409, "This username is already taken.")

    user = User(
        username=validated.username,
        password_hash=hash_password(validated.password),
        role="viewer",
        is_active=True,
        must_change_password=False
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user

# ------------------------------------------------------------ user management
def _active_admins(db: Session) -> int:
    return db.query(User).filter(User.role == "admin", User.is_active.is_(True)).count()


@router.get("/users", response_model=List[UserOut])
def list_users(_admin=Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(User).order_by(User.id).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, _admin=Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(User).filter(func.lower(User.username) == body.username.lower()).first():
        raise HTTPException(409, f"Username '{body.username}' is already taken")
    user = User(username=body.username, password_hash=hash_password(body.password), role=body.role)
    db.add(user)
    db.commit()
    return user


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, admin=Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    changes = body.model_dump(exclude_unset=True)
    demoting = user.role == "admin" and (changes.get("role") == "viewer" or changes.get("is_active") is False)
    if demoting and _active_admins(db) <= 1:
        raise HTTPException(400, "You cannot remove the last active administrator.")
    if "role" in changes and changes["role"] != user.role:
        user.role = changes["role"]
        user.token_version = (user.token_version or 0) + 1
    if "is_active" in changes and changes["is_active"] != user.is_active:
        user.is_active = changes["is_active"]
        user.token_version = (user.token_version or 0) + 1
    if changes.get("password"):
        user.password_hash = hash_password(changes["password"])
        user.must_change_password = True                       # admin-set passwords must be changed by the user
        user.token_version = (user.token_version or 0) + 1
    db.commit()
    return user


@router.delete("/users/{user_id}")
def delete_user(user_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == getattr(admin, "id", None):
        raise HTTPException(400, "You cannot delete your own account.")
    if user.role == "admin" and user.is_active and _active_admins(db) <= 1:
        raise HTTPException(400, "You cannot remove the last active administrator.")
    db.delete(user)
    db.commit()
    return {"message": f"User '{user.username}' deleted", "id": user_id}
