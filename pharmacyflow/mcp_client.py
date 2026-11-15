import json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from .config import settings
from .security import Principal, token
from .leases import lease_owner


class Tools:
    def __init__(self, case, agent):
        self.auth = token(
            Principal(
                sub="worker",
                tenant=case.tenant,
                role="worker",
                patient_id=case.patient_id,
                case_id=case.id,
                agent=agent,
                lease_owner=lease_owner.get(),
            ),
            "mcp",
            seconds=120,
        )

    async def call(self, tool_name, **arguments):
        async with streamablehttp_client(settings().mcp_url) as (read, write, _):
            async with ClientSession(read, write) as client:
                await client.initialize()
                result = await client.call_tool(tool_name, {"context_token": self.auth, **arguments})
        # Raise application rejections after transport task groups close. Otherwise
        # AnyIO wraps them in ExceptionGroup and obscures the bounded failure type.
        if result.isError:
            raise RuntimeError("MCP tool rejected: " + tool_name)
        if result.structuredContent:
            return result.structuredContent
        return json.loads(next(c.text for c in result.content if c.type == "text"))
