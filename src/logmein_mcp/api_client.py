import asyncio

import httpx

from ._json import error_envelope

_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_MAX_BACKOFF_SECONDS = 20.0

# status_code -> (error code, retryable). status_code 0 means a network/
# connection-level failure (no response at all). Login/report-state
# failures (§ below) are also mapped through here using a synthetic status
# code, since the Rescue API reports them as "OK"/"ERROR" text bodies on
# HTTP 200 rather than as real HTTP error statuses.
_STATUS_TO_CODE: dict[int, tuple[str, bool]] = {
    0: ("upstream_error", True),
    400: ("invalid_argument", False),
    401: ("unauthorized", False),
    403: ("unauthorized", False),
    404: ("not_found", False),
    422: ("invalid_argument", False),
    429: ("rate_limited", True),
}


def _classify(status_code: int) -> tuple[str, bool]:
    if status_code in _STATUS_TO_CODE:
        return _STATUS_TO_CODE[status_code]
    if status_code >= 500:
        return "upstream_error", True
    return "invalid_argument", False


class LogMeInError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"LogMeIn Rescue API error {status_code}: {message}")

    def to_envelope(self) -> str:
        code, retryable = _classify(self.status_code)
        return error_envelope(code, self.message, retryable)


class LogMeInClient:
    """Async httpx client wrapping the LogMeIn Rescue API.

    The Rescue API is a classic ASP.NET session-cookie API: `login.aspx`
    authenticates with email+password and sets an ASP.NET_SessionId cookie,
    which every subsequent `*.aspx` call relies on. There is no bearer
    token or API key.

    Unlike the Addigy/Cove reference clients, this client deliberately does
    **not** use a shared module-level `httpx.AsyncClient`. httpx's cookie
    jar lives on the client instance and is applied automatically to every
    request made through it — if the cookie-carrying client were shared
    across concurrent requests, one tenant's Rescue session cookie could
    get attached to another tenant's request (a cross-tenant leak, exactly
    what SOP §3.3/3.4 prohibits). Instead, every top-level call opens a
    fresh `httpx.AsyncClient` (fresh cookie jar), performs a fresh login,
    makes the real API call(s) on that same client/cookie jar, and then
    discards the whole thing — nothing is cached across requests or
    tenants. Connection reuse (§5) still happens *within* one tool
    invocation: `get_report`'s chained setReportArea/setReportDate/
    getReport_v2 calls all share the one client opened for that call.
    """

    def __init__(self, username: str, password: str, base_url: str):
        self._username = username
        self._password = password
        self._base_url = base_url.rstrip("/")

    def _clean(self, params: dict | None) -> dict:
        if not params:
            return {}
        return {k: v for k, v in params.items() if v is not None}

    async def _request(
        self, client: httpx.AsyncClient, method: str, params: dict | None = None
    ) -> str:
        """GET {base_url}/{method}.aspx with retry + backoff on network
        errors and 429/5xx, respecting Retry-After. Returns the raw text
        body on any non-retried response; raises LogMeInError for HTTP
        errors (status >= 400) or exhausted retries.
        """
        url = f"{self._base_url}/{method}.aspx"
        params = self._clean(params)

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await client.get(url, params=params)
            except httpx.RequestError as e:
                last_exc = e
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(min(2**attempt, _MAX_BACKOFF_SECONDS))
                    continue
                raise LogMeInError(0, f"{e or type(e).__name__} (method={method})") from e

            if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
                await asyncio.sleep(self._retry_delay(resp, attempt))
                continue

            if resp.status_code >= 400:
                raise LogMeInError(
                    resp.status_code, resp.text.strip() or f"HTTP {resp.status_code}"
                )
            return resp.text

        if last_exc:
            raise LogMeInError(0, f"{last_exc}") from last_exc
        raise LogMeInError(0, "request failed with no response")

    def _retry_delay(self, resp: httpx.Response, attempt: int) -> float:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), _MAX_BACKOFF_SECONDS)
            except ValueError:
                pass
        return min(2**attempt, _MAX_BACKOFF_SECONDS)

    async def _login(self, client: httpx.AsyncClient) -> None:
        body = await self._request(
            client, "login", {"email": self._username, "pwd": self._password}
        )
        body = body.strip()
        if body != "OK":
            # Wrong/expired credentials — surfaces as a business-level "login
            # failed" body on HTTP 200, so map it to unauthorized ourselves.
            raise LogMeInError(401, f"login failed: {body}")

    async def call(self, method: str, params: dict | None = None) -> str:
        """Log in, then call a single API method (used by session/chat/note)."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            await self._login(client)
            return await self._request(client, method, params)

    async def get_report(
        self,
        report_area: int,
        node: str,
        nodetype: str,
        begin_date: str | None,
        end_date: str | None,
    ) -> str:
        """Log in, set the report area (and optionally the date range), then
        retrieve the report. getReport_v2 depends on state set by prior
        setReportArea/setReportDate_v2 calls within the same session, so all
        of this happens on one shared client/cookie jar.
        """
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            await self._login(client)
            area_result = await self._request(client, "setReportArea", {"area": report_area})
            if area_result.strip() != "OK":
                # Bad report_area/node/nodetype combination.
                raise LogMeInError(400, f"setReportArea failed: {area_result.strip()}")
            if begin_date or end_date:
                date_result = await self._request(
                    client, "setReportDate_v2", {"bdate": begin_date, "edate": end_date}
                )
                if date_result.strip() != "OK":
                    raise LogMeInError(400, f"setReportDate_v2 failed: {date_result.strip()}")
            return await self._request(client, "getReport_v2", {"node": node, "nodetype": nodetype})
