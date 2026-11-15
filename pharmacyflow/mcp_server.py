from mcp.server.fastmcp import FastMCP
from .tool_service import invoke
from .config import settings

mcp = FastMCP(
    "PharmacyFlow synthetic scoped tools", host="0.0.0.0", port=settings().mcp_port, stateless_http=True
)


@mcp.tool()
def patient_lookup(context_token: str, name: str = "", dob: str = "") -> dict:
    """Find exact synthetic patient within the signed tenant/case scope."""
    return invoke(context_token, "patient_lookup", {"name": name, "dob": dob})


@mcp.tool()
def prescription_lookup(context_token: str) -> dict:
    """List prescriptions for the case's selected patient only."""
    return invoke(context_token, "prescription_lookup")


@mcp.tool()
def request_status(context_token: str) -> dict:
    """Reconcile the case's exact persisted external action."""
    return invoke(context_token, "request_status")


@mcp.tool()
def workflow_task(context_token: str) -> dict:
    """Read the bound workflow state; cannot mutate it."""
    return invoke(context_token, "workflow_task")


@mcp.tool()
def prepare_transaction(context_token: str) -> dict:
    """Prepare a short-lived UI capability after application authorization."""
    return invoke(context_token, "prepare_transaction")


if __name__ == "__main__":
    import sys
    from .config import settings

    settings().validate_runtime()
    from .telemetry import configure

    configure()
    mcp.run(transport="stdio" if "--stdio" in sys.argv else "streamable-http")
