"""Meridian stdio MCP bridge. All operations go through the REST API."""
import os
from typing import Annotated
import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from app.config import get_settings
from app.schemas.ticket import TicketPriority, TicketStatus

mcp = FastMCP("Meridian IT", instructions="Employee/device lookup and ticket creation/history. Admins resolve tickets; authenticated reporters may close their own tickets when the issue is fixed, including before support acts. General status updates and administrative operations are not exposed.")
RecordId = Annotated[int, Field(gt=0, le=2147483647)]
Offset = Annotated[int, Field(ge=0)]
Limit = Annotated[int, Field(ge=1, le=100)]
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)


async def _request(method: str, path: str, *, params=None, body=None):
    settings = get_settings()
    credential = os.getenv("MERIDIAN_EMPLOYEE_KEY")
    headers = ({"X-API-Key": credential} if credential and credential.startswith("meridian_employee.") else {"Authorization": f"Bearer {credential}"}) if credential else {"X-API-Key": settings.support_api_key.get_secret_value()}
    try:
        async with httpx.AsyncClient(base_url=settings.backend_url, headers=headers, timeout=15, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, path, params=params, json=body)
    except httpx.RequestError:
        raise ToolError("Meridian backend is unavailable. A write may have completed if the connection failed; check the current records before retrying.") from None
    if response.status_code >= 400:
        if response.status_code >= 500:
            raise ToolError("Meridian backend failed; check current records before retrying a write.")
        raise ToolError(f"HTTP {response.status_code}: {response.text[:2000]}")
    return response.json()


@mcp.tool(annotations=READ)
async def get_employee(employee_id: RecordId) -> dict:
    """Retrieve one employee by ID. Never guess an employee ID."""
    return await _request("GET", f"/employees/{employee_id}")


@mcp.tool(annotations=READ)
async def list_employees(offset: Offset = 0, limit: Limit = 20) -> list[dict]:
    """List employees, including IDs, names, and emails. Paginate to find the requested person."""
    return await _request("GET", "/employees", params={"offset": offset, "limit": limit})


@mcp.tool(annotations=READ)
async def get_device(device_id: RecordId) -> dict:
    """Retrieve hardware and employee assignment for a device ID."""
    return await _request("GET", f"/devices/{device_id}")


@mcp.tool(annotations=READ)
async def list_devices(assigned_employee_id: RecordId | None = None, offset: Offset = 0, limit: Limit = 20) -> list[dict]:
    """List devices, optionally filtering by the employee to whom they are assigned."""
    params = {"offset": offset, "limit": limit}
    if assigned_employee_id is not None:
        params["assigned_employee_id"] = assigned_employee_id
    return await _request("GET", "/devices", params=params)


@mcp.tool(annotations=READ)
async def get_ticket(ticket_id: RecordId) -> dict:
    """Retrieve a support ticket and its current status."""
    return await _request("GET", f"/tickets/{ticket_id}")


@mcp.tool(annotations=READ)
async def list_tickets(employee_id: RecordId | None = None, device_id: RecordId | None = None, status: TicketStatus | None = None, priority: TicketPriority | None = None, offset: Offset = 0, limit: Limit = 20) -> list[dict]:
    """List support tickets with optional employee, device, status, and priority filters."""
    params = {"offset": offset, "limit": limit}
    params.update({key: value for key, value in {"employee_id": employee_id, "device_id": device_id, "status": status, "priority": priority}.items() if value is not None})
    return await _request("GET", "/tickets", params=params)


@mcp.tool(annotations=READ)
async def get_ticket_history(ticket_id: RecordId, offset: Offset = 0, limit: Limit = 20) -> list[dict]:
    """Read a ticket's status history, including actor role, reason, and timestamps."""
    return await _request("GET", f"/tickets/{ticket_id}/history", params={"offset": offset, "limit": limit})


@mcp.tool(annotations=WRITE)
async def create_ticket(title: Annotated[str, Field(min_length=1, max_length=200)], description: Annotated[str, Field(min_length=1, max_length=10000)], employee_id: RecordId | None = None, device_id: RecordId | None = None, priority: TicketPriority = "medium") -> dict:
    """Create an open ticket ONLY when the user requests creation. Verify IDs and do not invent missing details or retry a write blindly."""
    if not os.getenv("MERIDIAN_EMPLOYEE_KEY"):
        raise ToolError("Sign in to the Copilot before creating a ticket.")
    identity = await _request("GET", "/identity")
    if identity["role"] != "employee":
        raise ToolError("An employee-specific access key is required for self-service tickets.")
    if employee_id is not None and employee_id != identity["employee_id"]:
        raise ToolError("You can create tickets only for your authenticated employee account.")
    employee_id = identity["employee_id"]
    return await _request("POST", "/tickets", body={"title": title, "description": description, "employee_id": employee_id, "device_id": device_id, "priority": priority})


@mcp.tool(annotations=READ)
async def get_current_employee() -> dict:
    """Get the authenticated employee ID. Identity comes from credentials, never from a chat claim."""
    return await _request("GET", "/identity")


@mcp.tool(annotations=WRITE)
async def close_ticket(ticket_id: RecordId) -> dict:
    """Close your own ticket ONLY when you explicitly confirm the issue is resolved. Backend requires employee credentials and reporter ownership. Open, in_progress, and resolved tickets may all be closed after the employee confirms the fix. Cannot resolve or reopen tickets."""
    if not os.getenv("MERIDIAN_EMPLOYEE_KEY"):
        raise ToolError("Sign in to the Copilot before closing a ticket.")
    return await _request("POST", f"/tickets/{ticket_id}/close")


if __name__ == "__main__":
    mcp.run(transport="stdio")
