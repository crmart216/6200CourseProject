# Run the chat project from its root folder

Copy compose.yaml beside your existing backend/ and frontend/ folders:

- ./compose.yaml (the downloaded file)
- ./backend/Dockerfile (existing)
- ./backend/... (existing backend source)
- ./frontend/Dockerfile (existing)
- ./frontend/server.mjs and other frontend source (existing)

Keep both Dockerfiles unchanged. This download contains configuration and instructions, not the application source.

## 1. Stop the old separate stacks

From the project root, stop whichever frontend configuration you previously used:

```bash
docker compose -f frontend/compose.yaml down
```

If you previously used the Linux host-network configuration instead, use its original invocation with `down`, for example:

```bash
docker compose -f frontend/compose.linux.yaml down
```

Stop the old backend:

```bash
docker compose -f backend/compose.yaml down
```

Do not add `-v`: that deletes Compose-managed database volumes.

## 2. Check the existing database volume

A Compose project previously launched from a folder named `backend` normally uses `backend_postgres_data`. The new root file explicitly reuses that name by default.

List volumes before starting:

```bash
docker volume ls
```

If your existing database volume has another name, create a `.env` file beside the new root compose.yaml with its exact name:

```dotenv
POSTGRES_VOLUME_NAME=your_actual_existing_volume_name
```

If the configured name does not exist, Compose creates a new empty volume. For a fresh installation, the default is fine. Existing database credentials must match the values in compose.yaml.

## 3. Build and run from ./

In the folder containing the new root compose.yaml:

```bash
docker compose config
docker compose build
docker compose up
```

Or start in the background:

```bash
docker compose up -d
```

Open:

- Frontend: http://localhost:3000
- API Swagger docs: http://localhost:8000/docs
- PostgreSQL from host tools: localhost:5433, database/user/password: chat

The root file replaces the separate Compose invocations. The files inside backend/ and frontend/ can remain, but are not loaded by this root configuration. Do not pass the frontend Linux override to the root invocation.

## How it works

Build contexts point to ./backend and ./frontend, so each Dockerfile still sees its original source folder. All services share the default Compose network. The frontend Node server reaches the API at http://api:8000; the API reaches Postgres at db:5432. No host networking or host.docker.internal mapping is needed.

The frontend must listen on 0.0.0.0 inside its container; host port publishing still limits access to 127.0.0.1. This configuration assumes server.mjs uses API_BASE_URL for server-side API forwarding, as your supplied environment settings suggest. Browser JavaScript cannot resolve the Docker service name api. If the frontend sends requests directly from the browser, use http://localhost:8000 as its browser-facing API URL and configure API CORS for http://localhost:3000 instead.

Startup order: healthy database, successful Alembic migration, listening API, frontend. The API check verifies its TCP listener, not full application/database functionality. The migrate container exiting with code 0 is expected.

The original database port mapping 5433:5433 was corrected to 5433:5432 because Postgres listens on port 5432 inside this container.

## Useful commands

```bash
docker compose ps -a
docker compose logs -f
docker compose down
docker compose up --build
```

`down` preserves the database volume; `down -v` deletes it.

## Validation

The YAML structure and dependency references were checked. Docker was unavailable in the preparation environment, and application source was not supplied, so image builds and runtime connectivity were not executed. Run `docker compose config` locally before building.

References:
- https://docs.docker.com/compose/how-tos/networking/
- https://docs.docker.com/compose/how-tos/startup-order/
