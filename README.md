# Meridian IT Management Backend

Standalone FastAPI/PostgreSQL backend for employees, devices, and IT support
tickets. The AI Copilot is a separate repository and communicates through MCP.

## Local Windows setup

Requires Python 3.12+, PostgreSQL, and a PostgreSQL administrator account.
In CMD:

```bat
cd /d C:\MeridianITBackend
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python scripts\setup_database.py
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --port 8000
```

The setup script prompts locally for the PostgreSQL administrator password. It
creates meridian_it and a dedicated meridian_app login, and writes generated
application credentials and support/admin keys to the ignored .env file. The
administrator password is not saved. The script refuses existing configuration,
roles, or databases rather than overwriting them.

For an existing database, configure .env from .env.example and provide distinct,
random SUPPORT_API_KEY and ADMIN_API_KEY values. Keep all credentials private.
Restart the API after changing configuration. No database files, credentials, or
virtual environments belong in Git.

Swagger: http://127.0.0.1:8000/docs

## API

| Resource | Operations |
| --- | --- |
| /health | Application health |
| /health/database | SQLAlchemy SELECT 1 check; 503 if unavailable |
| /employees | Create/list |
| /employees/{id} | Read/PATCH/delete |
| /employees/{id}/access-key | Admin-issued employee credential |
| /devices | Create/list; filter assigned_employee_id |
| /devices/{id} | Read/PATCH/delete |
| /tickets | Create/list; filter employee_id, device_id, status, priority |
| /tickets/{id} | Read/PATCH/admin-only delete |
| /tickets/{id}/admin | Admin edits and status overrides |
| /tickets/{id}/history | Ordered status history |
| /tickets/{id}/close | Reporter self-service closure |
| /identity | Role and employee ID from the request credential |

Lists use offset/limit (default 20, maximum 100), ordered by ID. Missing records
return 404, duplicate email/asset tags return 409, invalid inputs return 422.
Emails are normalized to lowercase and asset tags to uppercase by API schemas.
Devices may be unassigned or assigned to an existing employee. Tickets require
an employee and optionally reference a device, including shared devices.
Foreign keys block deletion of employees/devices referenced by tickets and
employees with assigned devices. Deactivate employees to preserve their records.

## Ticket permissions and workflow

New tickets start open. Normal administrator transitions are:

```text
open -> in_progress -> resolved -> closed
resolved -> in_progress
```

Administrators can override transitions with a reason through /admin. Changing
an existing ticket's reporter or priority and deleting tickets requires admin
access. Delete permanently removes the ticket and its history; prefer closure.

An authenticated reporting employee can create only for their own employee ID
and close their own ticket from open, in_progress, or resolved after fixing the
issue. They do not need to wait for support. Other status changes, reopening,
reassignment, edits, and deletion are not available to employee credentials.
POST /tickets/{id}/close and employee PATCH with only status=closed enforce the
same ownership checks. Another employee or service role is rejected with 403.
Repeated closure by the owner is a no-op.

Transitions lock and reload the ticket row, and commit the status/history event
atomically. History records the actual previous/new states, actor role, employee
actor ID when known, reason, and timestamp. Existing pre-history tickets have a
truthful migration baseline; earlier transitions are not invented. Direct SQL
writes bypass workflow services and must not be used by integrations.

## Employee credentials

1. In Swagger, Authorize using ADMIN_API_KEY from the local .env.
2. POST /employees/{employee_id}/access-key for the intended active employee.
3. Deliver the returned api_key privately to that employee.
4. Enter it in the Copilot sidebar's Employee access key field.

The signed bearer key expires after seven days. Deactivating the employee
invalidates access. Rotating ADMIN_API_KEY invalidates all employee keys.
Individual key revocation, password login, and account recovery are not yet
implemented. Do not enter keys as chat messages.

## MCP integration

The Copilot launches `.venv\Scripts\python -m app.mcp_server` as a stdio
subprocess; no separate MCP terminal is needed. The bridge calls this REST API
rather than importing the Copilot or accessing its database.

Ten selected tools: get_employee, list_employees, get_device, list_devices,
get_ticket, list_tickets, get_ticket_history, get_current_employee, create_ticket,
and close_ticket. No generic status update, delete, arbitrary HTTP, or SQL tool
is exposed. Self-service writes require employee credentials; legacy reads use
the support service key when no employee key is supplied.

Run Meridian on port 8000 and the Copilot API on port 8001. Integration and chat
startup instructions are in the separate Copilot repository:
https://github.com/rushberry02/enterprise-it-support-copilot/blob/main/docs/meridian-integration.md

## Migrations and tests

```bat
python -m alembic upgrade head
python -m alembic current
python -m alembic check
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

The tests use the configured PostgreSQL database and roll back their records.
Identity sequences may advance. Services commit writes explicitly; ORM timestamp
updates occur through SQLAlchemy. Direct SQL updates must maintain timestamps.
Migration 0005 refuses downgrade while employee closure history exists, so its
audit attribution cannot silently be destroyed.

## Development boundaries

Ticket mutation permissions and reporter closure ownership are enforced. The
older read and employee/device CRUD APIs retain their local development access
behavior; full user authentication/authorization across those APIs is unfinished.
This is a local development backend, not a production-hardened deployment.
