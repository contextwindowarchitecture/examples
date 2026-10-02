"""The application's side of MCP: one session with the fernway-api server for one agent run, through the official MCP
SDK over stdio. The server proposes tools and answers calls; it never sees a call the guard has not approved."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any

from mcp import Client, StdioServerParameters

SERVER = Path(__file__).parent / "mcp_servers" / "fernway_api.py"
SERVER_NAME = "fernway-api"


@dataclass(frozen=True)
class Result:
    ok: bool
    value: Any  # the tool's structured result, or the error text


class FernwayAPI:
    """async with FernwayAPI(faults) as api: proposed = await api.proposed(); result = await api.call(name, args)"""

    def __init__(self, faults: tuple[str, ...] | list[str] = ()) -> None:
        args = [str(SERVER)] + [arg for fault in faults if fault == "injected-response" for arg in ("--fault", fault)]
        self._client = Client(StdioServerParameters(command=sys.executable, args=args))

    async def __aenter__(self) -> FernwayAPI:
        await self._client.__aenter__()
        return self

    async def __aexit__(self, kind: type[BaseException] | None, error: BaseException | None, trace: TracebackType | None) -> None:
        await self._client.__aexit__(kind, error, trace)

    async def proposed(self) -> list[dict[str, Any]]:
        """The tools the server offers, as it describes them. Proposals only: the capability policy decides (R-15)."""
        listed = await self._client.list_tools()
        return [{"name": tool.name, "description": tool.description or "", "input_schema": tool.input_schema}
                for tool in listed.tools]

    async def call(self, name: str, arguments: dict[str, Any]) -> Result:
        result = await self._client.call_tool(name, arguments)
        if result.is_error:
            return Result(False, " ".join(getattr(block, "text", "") for block in result.content).strip())
        if result.structured_content is not None:
            return Result(True, result.structured_content)
        return Result(True, json.loads("".join(getattr(block, "text", "") for block in result.content) or "null"))
