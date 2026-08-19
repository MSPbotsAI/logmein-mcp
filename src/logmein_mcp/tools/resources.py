from collections.abc import Callable
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import cap_text
from ..api_client import LogMeInClient, LogMeInError
from ._common import NO_TOKEN


def register(mcp: FastMCP, client_factory: Callable[[], LogMeInClient | None]) -> None:

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def logmein_get_report(
        report_area: Annotated[
            Literal[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            Field(
                description=(
                    "Report type: 0 Session, 1 Customer Survey, 2 Login, "
                    "3 Missed Sessions, 4 Performance, 5 Chat Log, 6 Custom "
                    "Fields, 7 Transferred Sessions, 8 Technician Survey, "
                    "9 Collaboration Chatlog, 10 Failed Sessions."
                )
            ),
        ],
        node: Annotated[
            str,
            Field(
                description=(
                    "Node ID to scope the report to. Default -2 (whole "
                    "account, External Technicians root)."
                )
            ),
        ] = "-2",
        nodetype: Annotated[
            Literal["NODE", "CHANNEL", "EXTERNALROOT", "EXTERNALTECH", "EXTERNALGROUP"],
            Field(
                description=(
                    "Type of node: a single technician (NODE), CHANNEL, the "
                    "whole external-technician tree (EXTERNALROOT, default), "
                    "a single external technician (EXTERNALTECH), or an "
                    "external technician group (EXTERNALGROUP)."
                )
            ),
        ] = "EXTERNALROOT",
        begin_date: Annotated[
            str | None,
            Field(
                description=(
                    'Start of the report period, "M/D/YYYY H:MM:SS" (e.g. '
                    '"12/1/2011 8:00:00"). Omit to use the account\'s '
                    "currently configured date range."
                )
            ),
        ] = None,
        end_date: Annotated[
            str | None,
            Field(description="End of the report period, same format as begin_date."),
        ] = None,
    ) -> str:
        """Generate and retrieve a Rescue usage report for a report area, node, and date range.

        The vendor allows at most one report call per 60 seconds per account.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get_report(report_area, node, nodetype, begin_date, end_date)
            return cap_text(result)
        except LogMeInError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def logmein_get_session(
        node: Annotated[
            str, Field(description="The technician or channel node ID to list sessions for.")
        ],
        noderef: Annotated[
            Literal["NODE", "CHANNEL"],
            Field(description="Whether node is a technician (NODE, default) or a CHANNEL."),
        ] = "NODE",
    ) -> str:
        """List the current/recent sessions of a hierarchy node (technician or channel)."""
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.call("getSession_v3", {"node": node, "noderef": noderef})
            return cap_text(result)
        except LogMeInError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def logmein_get_chat(
        session: Annotated[
            str, Field(description="The session ID (get it from logmein_get_session).")
        ],
    ) -> str:
        """Retrieve the chat log of a specific Rescue session."""
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.call("getChat", {"session": session})
            return cap_text(result)
        except LogMeInError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def logmein_get_note(
        session: Annotated[
            str, Field(description="The session ID (get it from logmein_get_session).")
        ],
    ) -> str:
        """Retrieve the technician's note(s) for a specific Rescue session."""
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.call("getNote", {"session": session})
            return cap_text(result)
        except LogMeInError as e:
            return e.to_envelope()
