from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from ..api_client import LogMeInClient, LogMeInError
from ._common import NO_TOKEN


def register(mcp: FastMCP, client_factory: Callable[[], LogMeInClient | None]) -> None:

    @mcp.tool()
    async def logmein_get_report(
        report_area: int,
        node: str = "-2",
        nodetype: str = "EXTERNALROOT",
        begin_date: str | None = None,
        end_date: str | None = None,
    ) -> str:
        """Generate and retrieve a Rescue report (setReportArea + optional
        setReportDate_v2 + getReport_v2, chained on one logged-in session).

        API: GET setReportArea.aspx, setReportDate_v2.aspx, getReport_v2.aspx

        Args:
            report_area: Required. The report type to generate:
                0 - Session report
                1 - Customer Survey report
                2 - Login report
                3 - Missed Sessions report
                4 - Performance report
                5 - Chat Log report
                6 - Custom Fields report
                7 - Transferred Sessions report
                8 - Technician Survey report
                9 - Collaboration Chatlog report
                10 - Failed Sessions report
            node: Optional. Node ID to scope the report to. Default "-2"
                (the External Technicians root — reports across the whole
                account), matching MSPbots' own usage.
            nodetype: Optional. One of NODE (a single technician),
                CHANNEL, EXTERNALROOT (default — whole external-technician
                tree), EXTERNALTECH (a single external technician), or
                EXTERNALGROUP (an external technician group).
            begin_date: Optional. Start of the report period, "M/D/YYYY
                H:MM:SS" (e.g. "12/1/2011 8:00:00"). If omitted, the
                account's currently configured report date range is used.
            end_date: Optional. End of the report period, same format.

        Note: the vendor rate-limits report retrieval to once every 60
        seconds per account.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            return await client.get_report(report_area, node, nodetype, begin_date, end_date)
        except LogMeInError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def logmein_get_session(node: str, noderef: str = "NODE") -> str:
        """List the current/recent sessions of a hierarchy node (technician
        or channel), via getSession_v3.

        API: GET getSession_v3.aspx

        Args:
            node: Required. The technician or channel node ID to list
                sessions for.
            noderef: Optional. "NODE" (default, node is a technician) or
                "CHANNEL" (node is a channel).
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            return await client.call("getSession_v3", {"node": node, "noderef": noderef})
        except LogMeInError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def logmein_get_chat(session: str) -> str:
        """Retrieve the chat log of a specific session.

        API: GET getChat.aspx

        Args:
            session: Required. The session ID (get it from
                logmein_get_session).
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            return await client.call("getChat", {"session": session})
        except LogMeInError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def logmein_get_note(session: str) -> str:
        """Retrieve the technician's note(s) for a specific session.

        API: GET getNote.aspx

        Args:
            session: Required. The session ID (get it from
                logmein_get_session).
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            return await client.call("getNote", {"session": session})
        except LogMeInError as e:
            return f"Error: {e}"
