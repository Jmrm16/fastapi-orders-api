import bcrypt
from datetime import datetime, timedelta
from typing import Optional, Any, Union
from jose import jwt, JWTError
from app.config import settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain text password against its bcrypt hash."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8")
    )


def get_password_hash(password: str) -> str:
    """Generates a secure bcrypt hash for a plain password."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(
        password.encode("utf-8"),
        salt
    ).decode("utf-8")


def create_access_token(subject: Union[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Creates a signed JWT access token with an expiration timestamp."""
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """Decodes and validates a JWT token signature and expiration."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None
