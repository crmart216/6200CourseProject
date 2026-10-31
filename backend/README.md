# Group Chat API

A Python 3.11+ FastAPI REST backend with PostgreSQL, SQLAlchemy, Alembic migrations, and interactive Swagger documentation. Includes users, groups, memberships, and persisted messages.

## Start with Docker Compose

Install Docker with Compose v2, then from this folder run:

```bash
docker compose up --build
```

Compose starts PostgreSQL, waits for database health, runs `alembic upgrade head` in a separate migration container, then starts the API. PostgreSQL data persists in a named volume. API and database ports bind to localhost.

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi.json
- Liveness: http://localhost:8000/health (does not check the database)

The `chat:chat` database credentials are development defaults. This version intentionally has no authentication, authorization, transport encryption, or message encryption. Any caller can read or modify resources and impersonate a user through a supplied ID. Keep it in a local development environment until security is implemented.

## Local Python development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
docker compose up -d db
alembic upgrade head
uvicorn app.main:app --reload
```

On Windows, activate with `.venv\Scripts\activate`. For an existing PostgreSQL server, create an empty database and set `DATABASE_URL` in `.env` to `postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE`. Environment variables override `.env`; URL-encode special characters in credentials. The application and Alembic read the same settings. Alembic manages schema changes, not PostgreSQL server provisioning. Never call `create_all()` to initialize the production database.

`requirements-tested.txt` records the exact dependency versions used during verification. To reproduce them, install that file before `pip install -e '.[dev]'`.

## Architecture

Request flow: routes → controllers → services → repository → PostgreSQL.

| Directory | Responsibility |
| --- | --- |
| `app/routes/` | HTTP paths, request schemas, parameters, response models, dependency hooks |
| `app/controllers/` | One method per route; write transaction boundaries and conflict translation |
| `app/services/` | Group chat rules, existence checks, membership checks |
| `app/repository/` | Direct SQLAlchemy database queries; no commits |
| `app/models/` | SQLAlchemy table mappings |
| `app/schemas/` | Pydantic input/output validation and Swagger schemas |
| `app/db/` | Session factory and request-scoped session lifecycle |
| `app/core/` | Environment configuration |
| `app/middleware/` | Central place for future ASGI middleware registration |
| `migrations/` | Alembic environment and versioned migration scripts |
| `tests/` | API lifecycle, validation, conflicts, pagination, and schema tests |

Writes commit only after the service completes. Errors roll back the transaction. The repository performs database reads, inserts, deletes, and flushes; controllers own commits/rollbacks. Group and creator membership creation are one transaction. No application data queries are issued by routes.

## Routes

All chat routes are under `/api/v1`. UUID path parameters are used throughout.

| Method | Path | Behavior |
| --- | --- | --- |
| POST | `/users` | Create a user |
| GET | `/users` | List users |
| GET | `/users/{user_id}` | Retrieve a user |
| POST | `/groups` | Create a group and automatically join its creator |
| GET | `/groups` | List groups; optional `user_id` filter |
| GET | `/groups/{group_id}` | Retrieve a group |
| PUT | `/groups/{group_id}` | Replace name and description |
| DELETE | `/groups/{group_id}` | Delete group, memberships, and messages |
| POST | `/groups/{group_id}/members` | Add a user |
| GET | `/groups/{group_id}/members` | List memberships |
| DELETE | `/groups/{group_id}/members/{user_id}` | Remove a membership |
| POST | `/groups/{group_id}/messages` | Send a message |
| GET | `/groups/{group_id}/messages` | Read message history |
| GET | `/groups/{group_id}/messages/{message_id}` | Retrieve one message |
| PUT | `/groups/{group_id}/messages/{message_id}` | Replace message content |
| DELETE | `/groups/{group_id}/messages/{message_id}` | Delete one message |

List endpoints accept `limit` (1–100, default 50) and `offset` (0 or greater), and return JSON arrays. History is sorted oldest first by `(created_at, id)` for deterministic pagination. Clients can poll history for updates; this release does not include WebSockets or push delivery. Offset pagination can shift when messages are deleted, so clients should deduplicate by message ID and refresh history as needed.

Successful creates return 201, reads/updates 200, and deletes 204. Missing resources return 404, duplicate usernames/memberships and invalid sender membership return 409, and invalid request data returns 422. Domain error bodies have `{"detail": "..."}`; validation errors use FastAPI's standard detailed error array.

Usernames are case-sensitive and unique. Inputs reject unexpected fields. Names and message content cannot be blank; content is limited to 10,000 characters. Only current group members can be named as message senders; this is a data consistency rule, not identity verification. Removing a member preserves message history and blocks new sends using that membership. There are no owner/admin roles: `created_by` is historical metadata, and creators may leave. Groups may be empty. Membership rows are locked during send/remove to serialize these operations on PostgreSQL.

## Try it in Swagger

1. `POST /api/v1/users`:
   ```json
   {"username": "alice", "display_name": "Alice"}
   ```
2. Copy the returned `id`. `POST /api/v1/groups`:
   ```json
   {"name": "Study Group", "description": "Project discussion", "created_by": "PASTE_USER_UUID"}
   ```
3. Copy the returned group `id`. `POST /api/v1/groups/{group_id}/messages`:
   ```json
   {"sender_id": "PASTE_USER_UUID", "content": "Hello everyone!"}
   ```
4. `GET /api/v1/groups/{group_id}/messages` retrieves the stored message.
5. Create a second user and add them with `POST /api/v1/groups/{group_id}/members`, body `{"user_id": "SECOND_USER_UUID"}`.

Replace placeholder values with actual UUIDs. Swagger provides editable request bodies and complete response schemas for every route. A generated snapshot is also included at `docs/openapi.json`.

## Add security later

- Register global ASGI middleware in `app/middleware/setup.py`. This is called by the application factory before serving requests.
- Replace `security_hook` in `app/routes/dependencies.py` with an authentication dependency; it is already attached to the entire chat router.
- Pass a verified principal into controllers/services, and derive `sender_id` and `created_by` from that principal instead of trusting request bodies.
- Add resource-level authorization for group reads, membership changes, and message edits/deletes. Authentication middleware alone does not enforce those rules.
- For future cryptography, add separate payload/key services and explicit schema migrations. Current message content is plaintext; there is no forward secrecy or key management.

The hook currently does nothing. No JWT, passwords, encryption, permissions, or CORS policy have been implemented.

## Migrations

```bash
alembic upgrade head
alembic current
# After modifying SQLAlchemy models:
alembic revision --autogenerate -m "describe the schema change"
# Review the generated migration before applying it.
alembic upgrade head
alembic check
```

The initial migration has a downgrade, which **drops all four chat tables and their data**: use `alembic downgrade base` only on a disposable development database. Migration execution is intentionally separate from API startup so multiple API workers do not race to migrate.

## Tests and verification

```bash
pip install -e '.[dev]'
pytest -q
ruff check .
ruff format --check .
```

Default tests run against isolated in-memory SQLite databases with foreign keys enabled. To run the same API suite against PostgreSQL, create a **dedicated disposable test database**, then:

```bash
TEST_DATABASE_URL=postgresql+psycopg://chat:chat@localhost:5432/chat_test pytest -q
```

The PostgreSQL fixture applies Alembic migrations, wraps each test in a rollback transaction, and leaves the migrated empty schema in that test database. Do not point it at valuable data.

Verification performed for this deliverable: four API scenario tests passed on SQLite; lint and formatting passed; the initial migration generated PostgreSQL SQL successfully. Live PostgreSQL and Docker execution were unavailable in the build environment; PostgreSQL-specific locking and deployment must be exercised with the commands above.

## Reference documentation

- FastAPI middleware: https://fastapi.tiangolo.com/tutorial/middleware/
- Alembic migration environment: https://alembic.sqlalchemy.org/en/latest/tutorial.html
- Alembic autogeneration: https://alembic.sqlalchemy.org/en/latest/autogenerate.html
