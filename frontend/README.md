# Common — local group chat frontend

A standalone Node.js / TypeScript frontend for the **RSA group-key-escrow backend** supplied in `backend_with_rsa_group_keys.zip`. Runs as its own Docker image, without requiring any further backend modifications. No frontend framework or runtime npm dependencies are required. TypeScript compiles browser code; a Node HTTP server serves the UI and proxies `/api/v1/*` to the backend. Client-side messages use **AES-256-GCM**; the group key is exchanged with **RSA-OAEP-SHA256**.

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

## Use: Alice creates an encrypted group; Bob joins later

1. Start the **RSA-enabled backend** and this frontend, then open http://localhost:3000.
2. In one browser/profile (Alice), create or select Alice's user and **Create a group**. The browser retrieves `GET /api/v1/publickey`, generates a fresh random **32-byte AES key**, encrypts it with the server's RSA public key (RSA-OAEP with SHA-256), and sends `encrypted_group_key` in `POST /api/v1/groups`. The server stores the unwrapped key in the database and auto-joins Alice.
3. Send a message in Alice's group. The browser encrypts it with **AES-256-GCM**, a fresh 12-byte nonce, and a 128-bit authentication tag. Only ciphertext is sent as the message's `content`, in the string format `enc:v1:<base64 nonce>:<base64 AES-GCM ciphertext+tag>`.
4. In a **separate browser/profile or private window** (Bob), create/select Bob's user, open the group, and click **Join group**. Bob's browser creates/persists a private RSA-2048 key and sends the PEM public key as `public_key` in `POST /api/v1/groups/{id}/members`.
5. The server RSA-encrypts the stored AES group key for Bob and returns `encrypted_group_key`. Bob decrypts it locally with his private RSA key, caches a non-extractable AES key in IndexedDB, and can now read **all previous encrypted messages**. Bob's newly encrypted messages can also be read by Alice.
6. Reload either browser to see that local keys survive page reload. Edit/delete messages, edit/delete the group, leave, and refresh as before. **Editing encrypts the new text with a fresh nonce**; deletion only removes the ciphertext record.

The UI labels encrypted rooms **"AES-256-GCM · key escrowed by server (not end-to-end encrypted)"**. The original user picker remains a *demo convenience, not authentication*. Each browser/profile maintains its own RSA private keys and group keys, scoped by selected user; opening another browser as a user who is **already** a member will not automatically recover that member's key. To recover it with the current backend API, **leave and rejoin** that group using the new browser (membership join time resets). Do not clear browser site data if you need the locally stored keys and cannot rejoin.

### Previous plaintext groups

Groups created with the old frontend have no AES key and still work as plaintext groups. The backend returns no `encrypted_group_key` on their membership join; the frontend then remembers `legacy` mode. For pre-existing memberships on older groups with no saved browser access record, ciphertext history is clearly marked locked. If it is *actually an old plaintext group* and there is no encrypted history, select **Use legacy plaintext mode** to allow plaintext messages. Do **not** use this fallback for a new encrypted group missing its key: leave and rejoin instead. The backend currently does not expose a group-encryption indicator or a member-key-recovery endpoint, so the UI cannot safely distinguish empty legacy groups from encrypted groups with missing local keys on first load. The UI blocks sending in this ambiguous state until you explicitly choose a mode.

### API exchange with the RSA-enabled backend

| Action | Method / path after `/api/v1` | JSON body / response |
| --- | --- | --- |
| Get server's RSA public key | GET `/publickey` | Response: `public_key` (PEM) |
| Create user | POST `/users` | `username`, `display_name` |
| Create encrypted group | POST `/groups` | `name`, `description`, `created_by`, `encrypted_group_key` (RSA-OAEP-SHA256, base64) |
| Update group | PUT `/groups/{id}` | `name`, `description` |
| Join an encrypted group | POST `/groups/{id}/members` | `user_id`, `public_key` (PEM); response includes `encrypted_group_key` (RSA-OAEP-SHA256, base64) |
| Send encrypted message | POST `/groups/{id}/messages` | `sender_id`, `content` (AES-GCM serialized string) |
| Edit encrypted message | PUT `/groups/{id}/messages/{message_id}` | `content` (new AES-GCM serialized string) |

Group list/lookup and member/message CRUD endpoints retain their original shape. The backend also permits old plaintext clients. The frontend prevents accidental plaintext sends when it knows a group uses encryption, but **the backend does not cryptographically enforce encrypted messages**. Encrypted ciphertext must fit the server's 10,000-character `content` limit; very long plaintext drafts may exceed it after base64 encoding.

## Scope and behavior

This is a **deliberately insecure server-escrow demonstration**, not a production secure messenger and **not E2EE**. The backend holds the raw group AES key in its database and can decrypt every message. It has no authentication or authorization; selecting a user is not signing in. Message ownership controls in the UI are convenience controls, not authorization; backend authorization must be implemented separately. Group editing and deletion follow the unsecured API and are available to every local user. Chat text is rendered as text, not HTML.

Cryptographic operations require browser Web Crypto in a **secure context** (HTTPS or localhost). Browser IndexedDB stores non-extractable private RSA CryptoKeys and non-extractable AES CryptoKeys; keys are not written as PEM/raw base64 in `localStorage`. Keys are local to the browser profile and not synced between machines. The backend handles RSA key escrow; it does not decrypt message contents as part of message CRUD.

There is no WebSocket route in the supplied API, so this client uses polling. It reloads the entire selected conversation (including all pages) on each poll; this favors correctness and simplicity for local groups over scale. Offset pagination may momentarily shift under concurrent deletion; the next refresh resynchronizes. Failed sends retain the draft. Failed reads are reported and retried on the next poll. Network requests time out rather than hanging indefinitely.

## Checks and files

```sh
npm ci
npm run build
npm test
```

The `npm test` suite covers static serving, reverse-proxy behavior, RSA-OAEP-SHA256/AES-256-GCM wrapping and unwrapping, nonce uniqueness, tamper rejection, and encrypted-message size limits. There is also an optional **cross-language, live-backend integration test**, which creates two test users and a disposable group in your running database:

```sh
BACKEND_TEST_URL=http://localhost:3000 npm test
```

Both the local unit tests and the live integration test against the supplied FastAPI backend passed during implementation. A full browser-UI automated test could not run in the build environment because its installed Chromium has an administrator URL-blocking policy; TypeScript compilation and the live API tests passed. Docker was not run in this environment.

- `src/app.ts`: UI behavior, group creation/join exchange, client-side message encryption/decryption, polling and forms
- `src/crypto.ts`: browser Web Crypto RSA-OAEP-SHA256 and AES-256-GCM helpers
- `src/key-store.ts`: browser IndexedDB storage for non-extractable RSA/AES `CryptoKey` objects
- `public/app.js`, `public/crypto.js`, `public/key-store.js`: compiled, served ES modules
- `public/index.html`, `public/styles.css`: responsive UI with key-availability status
- `server.mjs`: static server and backend proxy
- `Dockerfile`: multi-stage build and unprivileged Node runtime
- `compose.yaml`: standard Docker host routing
- `compose.linux.yaml`: Linux localhost-only alternative
- `tests/crypto.test.mjs`: cross-implementation crypto tests
- `tests/live-backend.test.mjs`: optional real FastAPI integration test
- `tests/server.test.mjs`: Node HTTP/proxy integration tests

## Public read-only log viewer

With the updated backend and migration `0003` installed, visit
**http://localhost:3000/logs**. The minimal `/logs` page has a sidebar with
links to every group; `?group=UUID` is a permanent link to that group's log.
The chat page also links to public logs for each room. Logs update without
reloading approximately every 1.8 seconds (cursor-based polling).

The viewer uses `logs.html`, `logs.css`, and TypeScript source `src/logs.ts`
(compiled to `public/logs.js` with `npm run build`). The Node server serves
these assets and forwards `/api/v1/logs` to the existing backend as usual.
Neither the page nor its API endpoints require an identity, password, or
cookie. This purposely publishes the decrypted content of all logged messages.
Only use the application with demo data, not private communications.
