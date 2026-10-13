import os
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from .db import User, Session, session, lock_control, utcnow
from .config import JWT_HOURS

hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
bearer = HTTPBearer(auto_error=False)
_secret = None
MEDIA_TICKET_SECONDS = 1800
_dummy_hash = hasher.hash(secrets.token_urlsafe(24))
_attempts = defaultdict(deque)
_attempt_lock = threading.Lock()


def initialize_secret():
    global _secret
    configured = os.environ.get("JWT_SECRET")
    if configured and len(configured) < 32:
        raise RuntimeError("JWT_SECRET 至少需要 32 个字符")
    if configured:
        _secret = configured
        return
    with session() as db:
        control = lock_control(db, 3)
        value = dict(control.value)
        if not value.get("jwt_secret"):
            value["jwt_secret"] = secrets.token_urlsafe(48)
            control.value = value
        _secret = value["jwt_secret"]


def public_user(user):
    return dict(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
    )


def token(user):
    now = utcnow()
    return jwt.encode(
        {
            "sub": str(user.id),
            "ver": user.token_version,
            "iat": now,
            "exp": now + timedelta(hours=JWT_HOURS),
            "iss": "logistics-safety",
            "aud": "logistics-web",
        },
        _secret,
        algorithm="HS256",
    )


def media_ticket(user, relative_path):
    now = utcnow()
    return jwt.encode(
        {
            "sub": str(user.id),
            "ver": user.token_version,
            "path": relative_path,
            "iat": now,
            "exp": now + timedelta(seconds=MEDIA_TICKET_SECONDS),
            "iss": "logistics-safety",
            "aud": "logistics-media",
        },
        _secret,
        algorithm="HS256",
    )


def authenticate_media_ticket(raw, relative_path):
    try:
        payload = jwt.decode(
            raw,
            _secret,
            algorithms=["HS256"],
            issuer="logistics-safety",
            audience="logistics-media",
            options={"require": ["exp", "iat", "sub", "ver", "path"]},
        )
        if payload["path"] != relative_path:
            raise ValueError()
        with Session() as db:
            user = db.get(User, int(payload["sub"]))
            if user is None or user.token_version != payload["ver"]:
                raise ValueError()
            return user
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise HTTPException(401, "播放地址已过期，请重新打开视频")


def authenticate(raw):
    try:
        payload = jwt.decode(
            raw,
            _secret,
            algorithms=["HS256"],
            issuer="logistics-safety",
            audience="logistics-web",
            options={"require": ["exp", "iat", "sub", "ver"]},
        )
        with Session() as db:
            user = db.get(User, int(payload["sub"]))
            if user is None or user.token_version != payload["ver"]:
                raise ValueError()
            return user
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise HTTPException(
            401, "登录已过期，请重新登录", headers={"WWW-Authenticate": "Bearer"}
        )


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "请先登录", headers={"WWW-Authenticate": "Bearer"})
    return authenticate(credentials.credentials)


def operator(user=Depends(current_user)):
    if user.role not in {"admin", "operator"}:
        raise HTTPException(403, "仅管理员和操作员可执行此操作")
    return user


def admin(user=Depends(current_user)):
    if user.role != "admin":
        raise HTTPException(403, "仅管理员可执行此操作")
    return user


def verify(password, encoded):
    try:
        return hasher.verify(encoded or _dummy_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def limit_login(request: Request):
    key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _attempt_lock:
        # Evict expired keys as well as timestamps to keep remote input bounded.
        for old_key in list(_attempts):
            queue = _attempts[old_key]
            while queue and queue[0] < now - 300:
                queue.popleft()
            if not queue:
                del _attempts[old_key]
        queue = _attempts[key]
        if len(queue) >= 15 or len(_attempts) > 10000:
            raise HTTPException(429, "尝试次数过多，请五分钟后重试")
        queue.append(now)
