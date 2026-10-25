from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.core.config import settings
from app.core.exceptions import UnauthorizedException


def create_access_token(
    data: dict,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Creates an internal JWT token (useful for local dev, testing, or session tokens).
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")
    return encoded_jwt


def verify_token(token: str) -> dict[str, Any]:
    """
    Verifies an incoming Bearer token.
    If AUTH0_ENABLED is True, validates against Auth0 JWKS.
    Otherwise (Dev / Test mode), decodes HS256 or unverified claims for seamless local dev.
    """
    if not token:
        raise UnauthorizedException("No token provided")

    # If Auth0 is enabled, decode with Auth0 verification
    if settings.AUTH0_ENABLED:
        try:
            jwks_url = f"https://{settings.AUTH0_DOMAIN}/.well-known/jwks.json"
            jwks_client = jwt.PyJWKClient(jwks_url)
            signing_key = jwks_client.get_signing_key_from_jwt(token)

            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=settings.AUTH0_ALGORITHMS,
                audience=settings.AUTH0_API_AUDIENCE,
                issuer=settings.AUTH0_ISSUER,
            )
            return payload
        except Exception as e:
            raise UnauthorizedException(f"Invalid Auth0 token: {str(e)}") from e

    # Dev / Local mode: Check HS256 internal token or unverified decode
    try:
        # First attempt HS256 decode using local SECRET_KEY
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        return payload
    except jwt.PyJWTError:
        try:
            # Fallback for dev mode: decode without verification if local dev
            payload = jwt.decode(token, options={"verify_signature": False})
            return payload
        except Exception as e:
            raise UnauthorizedException(f"Malformed token: {str(e)}") from e
