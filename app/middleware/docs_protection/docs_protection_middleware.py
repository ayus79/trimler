"""
OpenAPI Docs Protection Middleware

This middleware protects the FastAPI documentation endpoints (/docs, /redoc, /openapi.json)
with password authentication (HTTP Basic Auth) and optional IP whitelisting.

Configuration (via environment variables):
- API_DOCS_USERNAME: Username for accessing docs (default: "admin")
- API_DOCS_PASSWORD: Password for accessing docs (required)
- API_DOCS_ALLOWED_IPS: Comma-separated list of allowed IPs (optional, if not set, all IPs are allowed after auth)
"""

import base64
import hmac
from fastapi import Request, status
from fastapi.responses import HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse
from app.utils.log_config import log_message
from app.config.settings import settings


class DocsProtectionMiddleware(BaseHTTPMiddleware):
    """
    Middleware to protect OpenAPI documentation endpoints with password authentication.
    Supports optional IP whitelisting.
    """

    # Routes that require protection
    PROTECTED_ROUTES = [
        "/docs",
        "/redoc",
        "/openapi.json",
    ]

    def __init__(
        self,
        app,
        enabled: bool = True,
        username: str = None,
        password: str = None,
        allowed_ips: str = None,
    ):
        super().__init__(app)
        self.enabled = enabled

        # Get configuration from parameters or environment variables
        self.username = username or settings.api_docs_username
        self.password = password or settings.api_docs_password
        allowed_ips_str = allowed_ips or settings.api_docs_allowed_ips

        # Parse allowed IPs from comma-separated string
        self.allowed_ips = []
        if allowed_ips_str:
            self.allowed_ips = [
                ip.strip() for ip in allowed_ips_str.split(",") if ip.strip()
            ]

        # Validate configuration
        if self.enabled and not self.password:
            log_message(
                "[Docs Protection Middleware] WARNING: API_DOCS_PASSWORD or DOCS_PASSWORD not set. Docs protection is disabled.",
                warning=True,
            )
            self.enabled = False

    async def dispatch(self, request: Request, call_next):
        """
        Main middleware logic with error handling to prevent app crashes

        Args:
            request: FastAPI request object
            call_next: Next middleware/route handler

        Returns:
            Response from next handler or 401/403 error response
        """
        try:
            denial_response = self._authorize(request)
        except Exception as e:
            # FAIL CLOSED. Previously this middleware swallowed any exception
            # and unlocked docs, which let an attacker reach /openapi.json by
            # triggering a malformed-header crash. /openapi.json is a complete
            # endpoint map and must not be reachable without auth.
            #
            # Scoped to just the auth DECISION (not call_next/the actual
            # request handling) - otherwise any unrelated exception thrown by
            # a normal route handler anywhere in the app would get caught
            # here too and misreported as a 401 auth failure instead of
            # surfacing as the real error.
            log_message(
                f"[Docs Protection Middleware] Error in middleware: {str(e)} | Type: {type(e).__name__} | Path: {request.url.path}",
                error=True,
            )
            return self._request_authentication()

        if denial_response is not None:
            return denial_response

        return await call_next(request)

    def _authorize(self, request: Request):
        """Returns None if the request should proceed, or a Response to
        short-circuit with (auth prompt, or the allowed-IP bypass path).
        Contains no I/O other than reading the request itself, so it's safe
        to wrap in a single fail-closed try/except.
        """
        # Check if protection is enabled
        if not self.enabled:
            return None

        # Allow OPTIONS requests (CORS preflight) to pass through
        if request.method == "OPTIONS":
            return None

        # Check if this is a protected route
        if not self._is_protected_route(request.url.path):
            return None

        # Get client IP address and host
        client_ip = self._get_client_ip(request)
        host_header = request.headers.get("Host", "")
        host = host_header.split(":")[0] if host_header else ""

        # Check IP whitelist first (if configured)
        if self.allowed_ips:
            allowed_list_lower = [ip.lower().strip() for ip in self.allowed_ips]

            # Check if client IP or host is in allowed list
            if (
                client_ip in self.allowed_ips
                or client_ip in allowed_list_lower
                or (
                    host.lower() in ["localhost", "127.0.0.1"]
                    and (
                        "localhost" in allowed_list_lower
                        or "127.0.0.1" in allowed_list_lower
                    )
                )
                or (
                    client_ip == "127.0.0.1"
                    and (
                        "127.0.0.1" in allowed_list_lower
                        or "localhost" in allowed_list_lower
                    )
                )
            ):
                log_message(
                    f"[Docs Protection Middleware] Allowed IP/host {client_ip}/{host} - bypassing authentication",
                    info=True,
                )
                return None

        # Check HTTP Basic Authentication
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            # Check if accessing via IP address - browsers often block Basic Auth for IPs
            if self._is_ip_address(host):
                return self._request_authentication_html(host_header, request.url.path)
            return self._request_authentication()

        # Parse Basic Auth
        try:
            auth_type, credentials = auth_header.split(" ", 1)
            if auth_type.lower() != "basic":
                return self._request_authentication()

            decoded = base64.b64decode(credentials).decode("utf-8")
            username, password = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError):
            return self._request_authentication()

        # Constant-time credential compare to avoid timing oracles.
        username_ok = hmac.compare_digest(
            username.encode("utf-8"), (self.username or "").encode("utf-8")
        )
        password_ok = hmac.compare_digest(
            password.encode("utf-8"), (self.password or "").encode("utf-8")
        )
        if not (username_ok and password_ok):
            log_message(
                f"[Docs Protection Middleware] Failed authentication attempt from IP {client_ip} for {request.url.path}",
                warning=True,
            )
            return self._request_authentication()

        # Authentication successful
        log_message(
            f"[Docs Protection Middleware] Successful authentication from IP {client_ip} for {request.url.path}",
            info=True,
        )
        return None

    def _is_protected_route(self, path: str) -> bool:
        """
        Check if the route path is protected

        Args:
            path: Request URL path

        Returns:
            True if route is protected, False otherwise
        """
        # Normalize path - handle root_path prefix if present
        # FastAPI may include root_path in the request path
        normalized_path = path.rstrip("/")

        # Check against protected routes (both with and without root_path)
        for protected_path in self.PROTECTED_ROUTES:
            # Check exact match
            if normalized_path == protected_path or normalized_path.endswith(
                protected_path
            ):
                return True
            # Check if path starts with protected path
            if normalized_path.startswith(protected_path + "/"):
                return True

        return False

    def _get_client_ip(self, request: Request) -> str:
        """
        Extract client IP address from request

        Args:
            request: FastAPI request object

        Returns:
            Client IP address as string
        """
        # Check for forwarded IP (when behind proxy/load balancer)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # X-Forwarded-For can contain multiple IPs, take the first one
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

        # Fallback to direct client IP
        if request.client:
            return request.client.host

        return "unknown"

    def _is_ip_address(self, host: str) -> bool:
        """
        Check if the host is an IP address (IPv4)

        Args:
            host: Host string to check

        Returns:
            True if host is an IP address, False otherwise
        """
        if not host:
            return False
        parts = host.split(".")
        if len(parts) != 4:
            return False
        try:
            return all(0 <= int(part) <= 255 for part in parts)
        except ValueError:
            return False

    def _request_authentication_html(self, host: str, path: str) -> HTMLResponse:
        """
        Return HTML page explaining Basic Auth requirement for IP addresses
        Some browsers (especially Chrome) block Basic Auth prompts for IP addresses
        as a security measure, so we provide an HTML page with instructions.

        Args:
            host: The host that was accessed (IP address)

        Returns:
            HTMLResponse with instructions
        """
        # Try to construct localhost URL
        port = ""
        if ":" in host:
            port = ":" + host.split(":")[1]

        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Authentication Required</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            max-width: 600px;
            margin: 50px auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #d32f2f;
            margin-top: 0;
        }}
        .warning {{
            background-color: #fff3cd;
            border: 1px solid #ffc107;
            padding: 15px;
            border-radius: 4px;
            margin: 20px 0;
        }}
        .solution {{
            background-color: #d1ecf1;
            border: 1px solid #0c5460;
            padding: 15px;
            border-radius: 4px;
            margin: 20px 0;
        }}
        code {{
            background-color: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: monospace;
        }}
        a {{
            color: #1976d2;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔒 Authentication Required</h1>

        <div class="warning">
            <strong>⚠️ Browser Security Restriction:</strong><br>
            You're accessing this API documentation via an IP address (<code>{host}</code>).
            Some browsers (especially Chrome) block Basic Authentication prompts for IP addresses
            as a security measure.
        </div>

        <div class="solution">
            <strong>✅ Solution:</strong><br>
            Please use <code>localhost</code> instead of the IP address:
            <br><br>
            <a href="http://localhost{port}{path}" style="font-size: 16px; font-weight: bold;">
                http://localhost{port}{path}
            </a>
            <br><br>
            Or manually enter credentials in the URL:
            <br>
            <code>http://username:password@localhost{port}{path}</code>
        </div>

        <p><strong>Alternative:</strong> You can also try:</p>
        <ul>
            <li>Using a different browser (Firefox, Safari)</li>
            <li>Clearing browser cache for this IP address</li>
            <li>Using an incognito/private window</li>
        </ul>
    </div>
</body>
</html>
        """
        return HTMLResponse(
            content=html_content,
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": 'Basic realm="API Documentation"'},
        )

    def _request_authentication(self) -> StarletteResponse:
        """
        Return 401 response requesting HTTP Basic Authentication
        Uses Starlette Response directly to ensure proper header handling

        Note: Using Starlette Response directly ensures the WWW-Authenticate
        header is properly set and not modified by other middleware.

        The response must have:
        - Status code 401
        - WWW-Authenticate header with Basic realm
        - Empty or minimal body

        Browser Note: Browsers treat localhost and 127.0.0.1 as different origins.
        If the prompt doesn't appear for 127.0.0.1, clear browser cache or use
        localhost instead. Some browsers are stricter with IP addresses.

        Returns:
            Response with 401 status and WWW-Authenticate header
        """
        # Create response with headers set at initialization
        # This ensures headers are not stripped by CORS or other middleware
        headers = {
            "WWW-Authenticate": 'Basic realm="API Documentation"',
            "Content-Type": "text/plain",
        }
        response = StarletteResponse(
            content="Unauthorized",  # Some browsers need non-empty content
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers=headers,
            media_type="text/plain",
        )
        return response
