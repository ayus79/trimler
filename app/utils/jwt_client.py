from datetime import datetime, timedelta, timezone
import os
from typing import Dict, Optional
import jwt
import uuid
from jwt import ExpiredSignatureError, InvalidTokenError
from app.utils.log_config import log_message


class JwtTokenManager:
    """
    Manages JSON Web Tokens (JWT) for authentication and authorization.
    """

    def __init__(
        self,
        access_expiry: int = 0,
        refresh_expiry: int = 0,
        secret_key: Optional[str] = None,
        algorithm: str = "HS256",
        audience: Optional[str] = None,
        issuer: Optional[str] = None,
    ):
        # Resolve env vars at call time, not at class-definition time, so a
        # rotated JWT_SECRET_KEY actually takes effect for newly-built managers.
        self.secret_key = secret_key or os.getenv("JWT_SECRET_KEY")
        if not self.secret_key:
            raise ValueError("JWT_SECRET_KEY is not set")
        self.algorithm = algorithm
        self.audience = audience or os.getenv("JWT_AUDIENCE")
        self.issuer = issuer or os.getenv("JWT_ISSUER")
        self.access_token_time = timedelta(seconds=access_expiry)
        self.refresh_token_time = timedelta(seconds=refresh_expiry)

    def _create_token(self, data: Dict, lifetime: timedelta) -> Dict:
        """Generate a JWT token with jti."""
        expiration = datetime.now(timezone.utc) + lifetime

        payload = {
            # do NOT overwrite if caller already passed jti
            "jti": data.get("jti", uuid.uuid4().hex),
            "iat": datetime.now(timezone.utc),
            "exp": expiration,
            **data,
        }
        if self.audience and "aud" not in payload:
            payload["aud"] = self.audience
        if self.issuer and "iss" not in payload:
            payload["iss"] = self.issuer

        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

        return {
            "token": token,
            "expire_at": expiration,
            "updated_at": datetime.now(timezone.utc),
            "jti": payload["jti"],  # convenient to return
        }

    def create_access_token(self, data: Dict) -> Dict:
        """Generate an access token."""
        return self._create_token(data, self.access_token_time)

    def create_refresh_token(self, data: Dict) -> Dict:
        """Generate a refresh token."""
        return self._create_token(data, self.refresh_token_time)

    def verify_token(self, token: str, verify_exp: bool = True) -> Optional[Dict]:
        """Verify and decode a JWT token.

        Verifies signature, expiry, and - when configured - audience and
        issuer. `audience`/`issuer` come from constructor or env vars; when
        set, tokens minted for a different service are rejected (prevents
        cross-service token replay when services share a secret).
        """
        try:
            decode_kwargs = {
                "algorithms": [self.algorithm],
                "options": {"verify_exp": verify_exp},
            }
            if self.audience:
                decode_kwargs["audience"] = self.audience
            if self.issuer:
                decode_kwargs["issuer"] = self.issuer
            return jwt.decode(token, self.secret_key, **decode_kwargs)
        except ExpiredSignatureError:
            # Don't echo any portion of the token to logs - even the prefix
            # leaks header+payload bytes which include the user identifier.
            log_message("JWT token expired", warning=True)
            return None
        except InvalidTokenError as e:
            log_message(f"JWT token invalid: {str(e)}", warning=True)
            return None

    def is_token_expired(self, token: str) -> bool:
        """Check if a token is expired."""
        payload = self.verify_token(token, verify_exp=False)
        if not payload or "exp" not in payload:
            return True
        expiration_time = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        return datetime.now(timezone.utc) > expiration_time
