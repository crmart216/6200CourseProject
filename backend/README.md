# Group Chat API

A Python 3.11+ FastAPI REST backend with PostgreSQL, SQLAlchemy, Alembic migrations, and interactive Swagger documentation. Includes users, groups, memberships, persisted messages, and an **optional, intentionally insecure server-escrowed group-key exchange** using RSA-OAEP-SHA256.

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

The `chat:chat` database credentials are development defaults. This version intentionally has no authentication, authorization, transport encryption, or backend-side message encryption. Any caller can read or modify resources and impersonate a user through a supplied ID. Keep it in a local development environment until security is implemented.

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

On Windows, activate with `.venv\Scripts\activate`. For an existing PostgreSQL server, create an empty database and set `DATABASE_URL` in `.env` to `postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE`. Environment variables override `.env`; URL-encode special characters in credentials. The application and Alembic read the same settings. Set `SERVER_PRIVATE_KEY_PATH` to the path at which the server should retain its RSA private key (default `keys/server_private_key.pem`). Never commit that file. Alembic manages schema changes, not PostgreSQL server provisioning. Never call `create_all()` to initialize the production database.

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
| GET | `/publickey` | Return the persistent server PEM RSA public key |
| POST | `/users` | Create a user |
| GET | `/users` | List users |
| GET | `/users/{user_id}` | Retrieve a user |
| POST | `/groups` | Create a group and automatically join its creator; optional `encrypted_group_key` |
| GET | `/groups` | List groups; optional `user_id` filter |
| GET | `/groups/{group_id}` | Retrieve a group |
| PUT | `/groups/{group_id}` | Replace name and description |
| DELETE | `/groups/{group_id}` | Delete group, memberships, and messages |
| POST | `/groups/{group_id}/members` | Add a user; encrypted groups require `public_key`, and return `encrypted_group_key` |
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
- Group-key escrow is deliberately insecure: server has the raw group key, there is no authentication or forward secrecy, and messages are not encrypted by the API. Clients must encrypt message content themselves.

The hook currently does nothing. No JWT, passwords, identity verification, resource-level permissions, or CORS policy have been implemented.

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

Run the existing API tests and the new RSA key-exchange tests. The new tests cover key persistence, key wrapping, invalid keys, server non-disclosure, past-message decryption, and backward compatibility. Use PostgreSQL and Docker in your own environment for deployment-specific verification.

## Reference documentation

- FastAPI middleware: https://fastapi.tiangolo.com/tutorial/middleware/
- Alembic migration environment: https://alembic.sqlalchemy.org/en/latest/tutorial.html
- Alembic autogeneration: https://alembic.sqlalchemy.org/en/latest/autogenerate.html

## Optional RSA group-key exchange (insecure group messaging demonstration)

The RSA keypair is generated automatically on the first public-key or encrypted-group request. The **2048-bit RSA modulus** is used with **RSA-OAEP and SHA-256** (including SHA-256 in MGF1). "RSA-256" is not a usable secure RSA key size; the **256 bits** here refer to SHA-256 and the **32-byte AES-256 symmetric group key**. The server public key is returned as PEM. The private key is written to `SERVER_PRIVATE_KEY_PATH` with file mode 0600 and must be retained across restarts. The Docker Compose API service mounts a persistent `server_keys` volume at `/app/keys`. Do not delete or replace a production/demo server private key while groups depend on it for wrapping new members' keys.

**Alice creates a new encrypted group:**

1. `GET /api/v1/publickey` returns JSON `{ "public_key": "-----BEGIN PUBLIC KEY-----\n..." }`.
2. Alice creates a random **32-byte** symmetric key using a cryptographically secure RNG (e.g., Web Crypto `crypto.getRandomValues(new Uint8Array(32))`). She imports the PEM server public key as RSA-OAEP with SHA-256 and encrypts the 32 bytes using that key.
3. Alice sends `POST /api/v1/groups`:

   ```json
   {
     "name": "Encrypted Study Group",
     "description": "Demo",
     "created_by": "ALICE_USER_UUID",
     "encrypted_group_key": "BASE64_RSA_OAEP_SHA256_CIPHERTEXT"
   }
   ```

4. The server decrypts the ciphertext and stores the **raw** symmetric key in the group row (`groups.symmetric_key`). The key is never exposed through a group list/get/create response. The creator is joined as before.

**Bob joins later:**

1. Bob generates his own RSA keypair (2048 bits or larger) and retains his private key client-side.
2. Bob sends `POST /api/v1/groups/{group_id}/members`:

   ```json
   {
     "user_id": "BOB_USER_UUID",
     "public_key": "-----BEGIN PUBLIC KEY-----\nBOBS_PEM_KEY\n-----END PUBLIC KEY-----\n"
   }
   ```

3. A `201` response includes the original membership fields and `"encrypted_group_key": "BASE64_RSA_OAEP_SHA256_CIPHERTEXT_FOR_BOB"`. The server encrypts the stored group key with Bob's public key; Bob base64-decodes this value and decrypts it locally with his RSA private key (RSA-OAEP-SHA256). The server does **not** return Bob's plaintext group key.
4. Bob can decrypt older message ciphertext **only if the clients encrypted the messages using this group key in the first place**. The message CRUD APIs intentionally remain unchanged: `content` is an opaque string, suitable for base64-encoded AES-GCM payloads, but the existing frontend still sends and displays plaintext.

**Backward compatibility:** `encrypted_group_key` at group creation is optional. Omitting it creates a legacy group with `groups.symmetric_key = NULL`, so the supplied `frontend.zip` and its existing `POST /groups` / `POST /members` calls keep working without modification. For encrypted groups, `public_key` is mandatory when joining; a missing or malformed key receives HTTP 422, and no membership is created. Bad or non-AES-256 group ciphertext also receives HTTP 422. An unencrypted group join remains a normal `201` membership response without an `encrypted_group_key` field. No other endpoint's payload or CRUD semantics changed.

**Important limitations:** This demonstrates an insecure group system, **not** end-to-end encryption. The server can read every group's raw symmetric key; an attacker who gains access to the database, or who can impersonate a user to join a group, can recover message keys. Removed members retain keys they already received, and new members receive the same key used for historical messages (no key rotation or forward secrecy). Transport TLS, identity authentication, and access control are not provided. Keep deployments to a trusted local environment for teaching/demonstration.

## Public activity audit log (added in migration `0003`)

**Intentional disclosure:** `/api/v1/logs` and `/api/v1/logs/groups` are public
and include **decrypted message plaintext**. Do not use this feature for real
secret messages. Run `alembic upgrade head` before starting the updated API.
The new table starts empty; existing chat records are preserved and historical
messages are not backfilled. Existing messages are logged when served again.

| Request | Behavior |
| --- | --- |
| `GET /api/v1/logs?after=0&limit=200` | Public cursor-based audit events (UTC timestamps, ascending ID) |
| `GET /api/v1/logs?group_id=UUID&after=N` | Events for one group, including deleted groups |
| `GET /api/v1/logs/groups` | Group names/IDs for the frontend sidebar |
| `POST /api/v1/key-events/identity-generated` | Client reports locally generated RSA public key (`user_id`, `public_key`) |

Server key creation, server-public-key distribution, group key wrapping/receipt,
group key distribution to new members, message receipt and message delivery,
message edits/deletes, and group/member changes create immutable audit events.
Messages include original ciphertext and decrypted plaintext when possible.
No private keys or raw AES keys are included. Decryption uses the server's
escrowed group key and recognizes `enc:v1:nonce:ciphertext` as well as old
`base64(nonce || ciphertext)` AES-GCM messages. Client key-generation reports
are **untrusted self-reports** because there is no authentication.

The backend records a batch `messages_sent` event for each nonempty
`GET /groups/{id}/messages` response, including a snapshot of every message
served in that batch. Repeated chat polling means repeated delivery records,
so this is deliberately verbose and requires storage management in a longer
running deployment.
