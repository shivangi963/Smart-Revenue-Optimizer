"""Authentication & authorisation.

* Passwords: salted PBKDF2-HMAC-SHA256 (standard library, no extra dependency).
* Sessions: signed JWT (HS256) with an expiry. Each token carries the user's `token_version`, so
  changing a password / deactivating a user instantly invalidates all their old tokens.
* Roles: `admin` (everything) and `viewer` (read-only).
* Brute-force protection: 5 wrong passwords in 5 minutes locks that username+IP for 5 minutes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import jwt
from fastapi import Depends, Header, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User
from .utils.timeutils import utcnow

ALGORITHM = "HS256"
ROLES = ("admin", "viewer")
DEFAULT_ADMIN_PASSWORD = "admin123"          # demo default - flagged "must change" in the UI
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


# ----------------------------------------------------------------- passwords
def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def hash_password(password: str, iterations: Optional[int] = None) -> str:
    iterations = iterations or settings.password_hash_iterations
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, digest = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


_DUMMY_HASH = None


def dummy_verify(password: str) -> None:
    """Burn the same time as a real check so 'unknown user' and 'wrong password' look identical."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("not-a-real-password")
    verify_password(password, _DUMMY_HASH)


# -------------------------------------------------------------------- tokens
def create_token(user: User) -> str:
    now = int(time.time())
    payload = {"sub": str(user.id), "role": user.role, "tv": user.token_version, "iat": now,
               "exp": now + settings.token_expire_minutes * 60}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])   # algorithm pinned
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Your session has expired. Please sign in again.",
                            headers={"WWW-Authenticate": "Bearer"})
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid authentication token.", headers={"WWW-Authenticate": "Bearer"})


# ------------------------------------------------------------- brute force
class LoginThrottle:
    MAX_FAILURES = 5
    WINDOW = 300.0

    def __init__(self) -> None:
        self._fails: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> int:
        """Seconds until the lock ends (0 = not locked)."""
        now = time.time()
        with self._lock:
            recent = [t for t in self._fails.get(key, []) if now - t < self.WINDOW]
            self._fails[key] = recent
            if len(recent) >= self.MAX_FAILURES:
                return int(self.WINDOW - (now - recent[0])) + 1
        return 0

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._fails.setdefault(key, []).append(time.time())

    def clear(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


login_throttle = LoginThrottle()


# ------------------------------------------------------------ dependencies
@dataclass
class AnonymousAdmin:
    """Returned when AUTH_ENABLED=false (local development only)."""
    id: int = 0
    username: str = "anonymous"
    role: str = "admin"
    is_active: bool = True
    must_change_password: bool = False


def _user_from_token(token: str, db: Session) -> User:
    payload = decode_token(token)
    try:
        user = db.get(User, int(payload["sub"]))
    except (KeyError, ValueError, TypeError):
        raise HTTPException(401, "Invalid authentication token.", headers={"WWW-Authenticate": "Bearer"})
    if not user or not user.is_active or user.token_version != payload.get("tv"):
        raise HTTPException(401, "Your session is no longer valid. Please sign in again.",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


def get_current_user(token: Optional[str] = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    if not settings.auth_enabled:
        return AnonymousAdmin()
    if not token:
        raise HTTPException(401, "Please sign in.", headers={"WWW-Authenticate": "Bearer"})
    return _user_from_token(token, db)


def require_admin(user=Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Administrator access is required for this action.")
    return user


def require_ingest(x_api_key: Optional[str] = Header(default=None), token: Optional[str] = Depends(oauth2_scheme),
                   db: Session = Depends(get_db)):
    """POST /signals: an admin login OR the configured INGEST_API_KEY."""
    if not settings.auth_enabled:
        return AnonymousAdmin()
    if settings.ingest_api_key and x_api_key and hmac.compare_digest(x_api_key, settings.ingest_api_key):
        return AnonymousAdmin(username="ingest-api-key")
    if not token:
        raise HTTPException(401, "Sign in or send a valid X-API-Key header.", headers={"WWW-Authenticate": "Bearer"})
    user = _user_from_token(token, db)
    if user.role != "admin":
        raise HTTPException(403, "Administrator access is required for this action.")
    return user


# --------------------------------------------------------------- bootstrap
def ensure_default_admin(db: Session) -> Optional[str]:
    """First run: create the admin account. Returns a warning message if the default password is in use."""
    if db.query(User).count() > 0:
        return None
    from_env = bool(settings.admin_password)
    password = settings.admin_password or DEFAULT_ADMIN_PASSWORD
    db.add(User(username=settings.admin_username, password_hash=hash_password(password), role="admin",
                must_change_password=not from_env))
    db.commit()
    if from_env:
        return None
    return (f"Created the first admin account '{settings.admin_username}' with the DEFAULT password "
            f"'{DEFAULT_ADMIN_PASSWORD}'. Sign in and change it (Account tab), or set ADMIN_PASSWORD in backend/.env.")
