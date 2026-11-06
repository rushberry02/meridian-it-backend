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

## Employee login

Login users are linked one-to-one to existing employees by users.employee_id;
email/name/department remain on employees. Passwords use Argon2id. An admin
provisions the account once; employees then use only work email and password.

To create/reset a login locally, run the hidden password prompt:

```bat
.venv\Scripts\python scripts\set_user_password.py --email rd@example.com --role employee
```

Use an existing employee email. For an admin account, use --role admin. Omit
--role when resetting a password to preserve the account's current role. The
command never takes a password as a command-line argument. Passwords must be
12-128 characters. No real employee password is set automatically by migrations.

Admins may alternatively POST /auth/users with employee_id, password, and role,
or PUT /auth/users/{employee_id}/password. Both require admin authentication.
Employees cannot register themselves as admins or reset another user's password.

| Route | Behavior |
| --- | --- |
| POST /auth/login | Email/password -> access JWT and rotating refresh credential |
| POST /auth/refresh | Rotate refresh credential; preserve session identity |
| POST /auth/logout | Revoke the complete login session; idempotent |
| GET /auth/me | Authenticated user's employee profile and role |

AUTH_JWT_SECRET is a random server-side secret in .env, generated during setup.
JWTs last 15 minutes; refresh sessions last seven days by default. Both durations
are configurable with ACCESS_TOKEN_MINUTES and REFRESH_SESSION_DAYS. JWTs verify
HS256, issuer, audience, expiry, subject and session claims. Each authenticated
request also checks the database user/session/employee state, so logout, password
reset, expired sessions, and disabled accounts reject previously issued JWTs.
Only hashes of refresh credentials are stored. Rotation is atomic; replay of an
already-used refresh credential revokes its entire session family. Five failed
password attempts lock the account for fifteen minutes. Login errors do not
reveal whether an account exists.

The Streamlit UI keeps tokens in server-side session state and refreshes them
automatically. Passwords and tokens do not go to the model or checkpoints. A
browser refresh/reopened tab may require another normal login; persistent browser
remember-me cookies are not implemented. Logout revokes server access and clears
the chat state. API clients send Authorization: Bearer <access JWT>.

Legacy employee keys are refused once a password account exists, and no new
legacy key can be issued for such an employee. Support/admin service keys remain
available for internal setup/administration; employees never need to see them.

## MCP integration

The Copilot launches `.venv\Scripts\python -m app.mcp_server` as a stdio
subprocess; no separate MCP terminal is needed. The bridge calls this REST API
rather than importing the Copilot or accessing its database.

Ten selected tools: get_employee, list_employees, get_device, list_devices,
get_ticket, list_tickets, get_ticket_history, get_current_employee, create_ticket,
and close_ticket. No generic status update, delete, arbitrary HTTP, or SQL tool
is exposed. Self-service requests carry the authenticated employee JWT privately through
MCP. Internal service calls can still use the support key.

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

Employee/device reads and all ticket records/history require authentication and
are scoped to the employee. Employee/device mutations and general ticket status
changes require an admin. Internal admin/support service keys retain trusted
operational access. This is a local development deployment; production requires
HTTPS, managed secrets, broader request-rate controls, monitoring, and an account
recovery process. SSO/MFA and persistent browser remember-me cookies are not part
of this implementation.

## Admin dashboard APIs

The Copilot admin workspace uses protected GET /admin/summary and paginated
/admin/tickets, /admin/employees, /admin/devices endpoints. Queues include total,
offset, limit and items, plus search and resource-specific filters. Every route
requires an admin role verified by the backend. Employee JWTs are rejected.
Mutations use the existing protected resource endpoints and ticket workflow
services; authenticated admin status events include actor_employee_id.
Dashboard/chat management does not require another PostgreSQL migration.

The login endpoint accepts optional role=employee or role=admin to support the
Copilot's two login choices. The role must match the stored account after valid
password verification; a mismatch returns 403 without issuing tokens. This field
never assigns or changes account privileges. Omitting it preserves API client
compatibility. No schema migration is required for the login-role selector.
