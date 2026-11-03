# Common — local group chat frontend

A standalone Node.js / TypeScript frontend for the supplied FastAPI routes. Runs as its own Docker image, with no backend modifications. No frontend framework or runtime npm dependencies are required. TypeScript compiles the browser code; a Node HTTP server serves the UI and proxies `/api/v1/*` to the backend.

## Start with Docker

Keep your backend running on HTTP port 8000. In this folder:

```sh
docker compose up --build -d
```

Open http://localhost:3000. The browser calls the frontend's `/api/v1` path; Node forwards those requests to `http://host.docker.internal:8000`, the Docker equivalent of the host address. `localhost` inside a normal container refers to the container itself. The standard configuration works with Docker Desktop and a host backend reachable through the Docker bridge (for example, a backend container publishing port 8000).

### Linux: backend bound only to localhost

Use this alternative **instead of** the default Compose file when your backend listens exclusively on `127.0.0.1:8000` on Linux:

```sh
docker compose -f compose.linux.yaml up --build -d
```

This uses host networking, forwards to `http://127.0.0.1:8000`, and binds the frontend to `127.0.0.1:3000`. It is suitable for a local Linux development machine. Stop with `docker compose -f compose.linux.yaml down` (or `docker compose down` for the standard configuration).

### Another backend address

For the standard Compose configuration:

```sh
API_BASE_URL=http://host.docker.internal:8000 docker compose up --build -d
```

Use the backend origin only, without `/api/v1`. If both containers share a Docker network, the backend service name can be used, for example `http://api:8000`. The proxy uses HTTP. It does not require FastAPI CORS changes because the browser communicates with the frontend origin.

## Run without Docker

Requires Node.js 22 or newer; the Docker image uses Node.js 24.

```sh
npm ci
npm run build
npm start
```

The default backend address outside Docker is `http://localhost:8000`. Visit http://localhost:3000. Optional environment variables are `API_BASE_URL`, `PORT` (default 3000), and `HOST` (default 0.0.0.0). Run `npm run build` after TypeScript changes; restart Node after server changes.

## Use

1. Create a user or select an existing user.
2. Create a group or open one from the list. The backend automatically joins the creator.
3. Click **Join group** to join an existing group.
4. Send messages. Open another browser or private window and select another user to try chatting.
5. Edit or delete your displayed messages, edit a group, leave it, or delete it with confirmation.

The selected user ID is remembered in localStorage. The UI displays membership and refreshes messages every three seconds while the tab is visible. The refresh button reloads users and groups. All collection endpoints are paginated in batches of 100, so conversations are not silently truncated to the first page.

## API contract

The request fields were checked against `app/schemas/chat.py` in the existing backend archive:

| Action | Method / path after `/api/v1` | JSON body |
| --- | --- | --- |
| Create user | POST `/users` | `username`, `display_name` |
| Create group | POST `/groups` | `name`, `description`, `created_by` |
| Update group | PUT `/groups/{id}` | `name`, `description` |
| Join group | POST `/groups/{id}/members` | `user_id` |
| Send message | POST `/groups/{id}/messages` | `sender_id`, `content` |
| Edit message | PUT `/groups/{id}/messages/{message_id}` | `content` |

Read models use `id` for users, groups, and messages; memberships use `user_id` and `group_id`. Message timestamps are `created_at` and optional `updated_at`. If your backend schemas have changed, update the types and payloads in `src/app.ts`.

## Scope and behavior

This is a local development client with no authentication. Selecting a user is not signing in. Message ownership controls in the UI are convenience controls, not authorization; backend authorization must be implemented separately. Group editing and deletion follow the unsecured API and are available to every local user. Chat text is rendered as text, not HTML.

There is no WebSocket route in the supplied API, so this client uses polling. It reloads the entire selected conversation (including all pages) on each poll; this favors correctness and simplicity for local groups over scale. Offset pagination may momentarily shift under concurrent deletion; the next refresh resynchronizes. Failed sends retain the draft. Failed reads are reported and retried on the next poll. Network requests time out rather than hanging indefinitely.

## Checks and files

```sh
npm run build
npm test
```

TypeScript compilation and Node integration tests passed during creation. Tests cover static assets, proxy request bodies/query strings, backend status preservation, 204 responses, and unavailable-backend handling. Docker could not be run in the creation environment. An automated browser test could not run because its Chromium executable was unavailable; no live-backend end-to-end verification is claimed.

- `src/app.ts`: UI behavior, API types, polling, forms
- `public/index.html`, `public/styles.css`: responsive UI
- `server.mjs`: static server and backend proxy
- `Dockerfile`: multi-stage build and unprivileged Node runtime
- `compose.yaml`: standard Docker host routing
- `compose.linux.yaml`: Linux localhost-only alternative
- `tests/server.test.mjs`: Node integration tests
