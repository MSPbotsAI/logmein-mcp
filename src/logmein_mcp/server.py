import contextvars
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .api_client import LogMeInClient
from .config import Settings

# Per-request credential isolation via contextvars.
# GatewayTokenMiddleware sets this before the MCP handler runs.
# Python asyncio copies context per task, so concurrent SSE connections are isolated.
_gateway_creds_var: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar(
    "logmein_gateway_creds", default=None
)


def get_client_from_context(settings: Settings) -> LogMeInClient | None:
    """Resolve the active LogMeInClient for the current request context."""
    creds = _gateway_creds_var.get()
    if not creds:
        return None
    username, password = creds
    return LogMeInClient(username, password, settings.logmein_base_url)


class GatewayTokenMiddleware:
    """ASGI middleware.

    Reads X-LogMeIn-Username and X-LogMeIn-Password (both required) from
    request headers and stores them in the contextvar. Returns 401 if
    either is missing on /mcp requests.
    """

    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        username = request.headers.get("x-logmein-username")
        password = request.headers.get("x-logmein-password")
        if not username or not password:
            response = JSONResponse(
                {
                    "error": "Missing credentials",
                    "message": (
                        "This server requires the X-LogMeIn-Username and "
                        "X-LogMeIn-Password headers"
                    ),
                    "required_headers": ["X-LogMeIn-Username", "X-LogMeIn-Password"],
                    "optional_headers": [],
                },
                status_code=401,
            )
            await response(scope, receive, send)
            return

        ctx_token = _gateway_creds_var.set((username, password))
        try:
            await self.app(scope, receive, send)
        finally:
            _gateway_creds_var.reset(ctx_token)


def create_mcp_server(settings: Settings) -> FastMCP:
    """Build the FastMCP server instance and register all LogMeIn Rescue tools."""
    # DNS-rebinding protection is a browser-oriented safeguard that rejects
    # non-localhost Host headers with 421. Disable it so the server works
    # correctly behind a reverse proxy or docker network.
    mcp = FastMCP(
        name="logmein-mcp",
        instructions=(
            "LogMeIn Rescue (part of GoTo) is a remote-support / screen-sharing "
            "platform technicians use to connect to customer devices, chat with "
            "end users, and log session notes. This server covers exactly the 4 "
            "Rescue API methods MSPbots' own integration is configured for: "
            "session listings, chat logs, session notes, and account-level "
            "reporting — not account/CRM administration. Typical flow: call "
            "logmein_get_session to find recent session IDs for a technician or "
            "channel node, then logmein_get_chat / logmein_get_note to pull the "
            "transcript or notes for a specific session. Use logmein_get_report "
            "for account-level reporting (report_area selects the report type: "
            "sessions, logins, chat logs, custom fields, etc.); the vendor "
            "allows at most one report call per 60 seconds per account, so "
            "avoid tight retry loops on it. Authentication is per-request: this "
            "server logs in to Rescue fresh on every tool call using the "
            "credentials supplied in that call's headers, and never caches a "
            "session across calls or tenants. All 4 tools are read-only."
        ),
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    client_factory: Callable[[], LogMeInClient | None] = lambda: get_client_from_context(settings)

    from .tools import resources

    resources.register(mcp, client_factory)

    return mcp
