import httpx


class LogMeInError(Exception):
    def __init__(self, message: str):
        super().__init__(f"LogMeIn Rescue API error: {message}")


class LogMeInClient:
    """Async httpx client wrapping the LogMeIn Rescue API.

    The Rescue API is a classic ASP.NET session-cookie API: `login.aspx`
    authenticates with email+password and sets an ASP.NET_SessionId cookie,
    which every subsequent `*.aspx` call relies on. There is no bearer
    token or API key — to stay stateless (no cached session across MCP
    calls, per SOP), this client performs a fresh login on every single
    tool invocation, then makes the real call(s) on that same
    httpx.AsyncClient (and therefore the same cookie jar) before discarding
    it. All responses are plain pipe-delimited text starting with "OK" (or
    a specific status word) on success, so they are returned as raw text
    rather than parsed.
    """

    def __init__(self, username: str, password: str, base_url: str):
        self._username = username
        self._password = password
        self._base_url = base_url.rstrip("/")

    def _clean(self, params: dict | None) -> dict:
        if not params:
            return {}
        return {k: v for k, v in params.items() if v is not None}

    async def _login(self, client: httpx.AsyncClient) -> None:
        try:
            resp = await client.get(
                f"{self._base_url}/login.aspx",
                params={"email": self._username, "pwd": self._password},
            )
        except httpx.RequestError as e:
            raise LogMeInError(f"{e or type(e).__name__} (login)") from e
        if resp.status_code >= 400:
            raise LogMeInError(f"HTTP {resp.status_code} during login: {resp.text}")
        body = resp.text.strip()
        if body != "OK":
            raise LogMeInError(f"login failed: {body}")

    async def _get(self, client: httpx.AsyncClient, method: str, params: dict | None = None) -> str:
        try:
            resp = await client.get(f"{self._base_url}/{method}.aspx", params=self._clean(params))
        except httpx.RequestError as e:
            raise LogMeInError(f"{e or type(e).__name__} (method={method})") from e
        if resp.status_code >= 400:
            raise LogMeInError(f"HTTP {resp.status_code} calling {method}: {resp.text}")
        return resp.text

    async def call(self, method: str, params: dict | None = None) -> str:
        """Log in, then call a single API method (used by session/chat/note)."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            await self._login(client)
            return await self._get(client, method, params)

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
        async with httpx.AsyncClient(timeout=30.0) as client:
            await self._login(client)
            area_result = await self._get(client, "setReportArea", {"area": report_area})
            if area_result.strip() != "OK":
                raise LogMeInError(f"setReportArea failed: {area_result.strip()}")
            if begin_date or end_date:
                date_result = await self._get(
                    client, "setReportDate_v2", {"bdate": begin_date, "edate": end_date}
                )
                if date_result.strip() != "OK":
                    raise LogMeInError(f"setReportDate_v2 failed: {date_result.strip()}")
            return await self._get(client, "getReport_v2", {"node": node, "nodetype": nodetype})
