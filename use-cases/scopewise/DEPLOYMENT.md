# Deploy an invite-only pilot

The deployment target is one app process and one local model service. Do not scale the app to multiple workers: the inference lock and Telegram background-task guard are process-local. SQLite stores durable data; conversations reset after a restart. This is not a claim of public production readiness.

## Local Docker (Mac / Docker Desktop)

Use the native Ollama app for Apple Silicon acceleration. Keep its endpoint private. From this directory, copy `.env.example` to `.env` if it does not already exist, then:

```bash
docker compose up -d --build
```

The app is bound only to `127.0.0.1:8080` and uses `host.docker.internal:11434` for Ollama. Stop an existing direct Uvicorn process on port 8080 first. If this private host connection does not work with your Ollama configuration, use the direct local Python run rather than exposing port 11434 to the internet.

## Linux private Ollama service

```bash
docker compose -f compose.yaml -f compose.ollama.yaml up -d --build
docker compose -f compose.yaml -f compose.ollama.yaml exec ollama ollama pull llama3.1:latest
docker compose -f compose.yaml -f compose.ollama.yaml exec ollama ollama pull nomic-embed-text:latest
```

The Ollama container has no published port; the app connects through the private Compose network. The default overlay is CPU-only. Configure GPU support for the actual host using [Ollama's official Docker instructions](https://docs.ollama.com/docker); GPU passthrough and capacity have not been validated here. Model weights have their own persistent volume. Review model licenses before distribution.

## HTTPS deployment

Obtain an authorized host with enough memory and a domain pointing to it. Hosting is not promised to be free. Do not place private student material in a public demonstration deployment.

Generate separate invitation and webhook secrets:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Set in the private `.env`:

```dotenv
SCOPEWISE_PRODUCTION=true
SCOPEWISE_DOMAIN=your-actual-domain.example
SCOPEWISE_PUBLIC_URL=https://your-actual-domain.example
SCOPEWISE_INVITATION=replace-with-a-generated-random-secret
```

Replace every placeholder. Do not use the local development invitation. With the private model overlay:

```bash
docker compose -f compose.yaml -f compose.ollama.yaml --profile tls up -d --build
```

Caddy exposes ports 80/443 and proxies the app; the app port remains loopback-only. Public DNS, inbound firewall access and certificate issuance must work for this host. Do not expose Ollama or mount the Docker socket into the app. Pin the validated base, proxy and model image digests for a release; development tags may change. Python dependency resolution is pinned in `uv.lock` and installed with `uv sync --frozen` ([uv container guidance](https://docs.astral.sh/uv/guides/integration/docker/)).

Production configuration fails at startup without HTTPS and a long invitation. Sessions use Secure, HttpOnly, SameSite=Strict cookies. Mutations require a CSRF token; cross-origin browser requests are rejected. The reverse proxy must preserve the `Origin` header. Do not trust client-provided forwarding headers; tune trusted proxy addresses deliberately if you need per-client IP rate limiting behind Caddy. With the conservative defaults, login attempts through the proxy may share a rate-limit bucket.

The app limits body bytes before JSON/multipart parsing. File parsing runs in an isolated subprocess with a timeout; Linux applies memory/CPU limits. The container runs as UID 10001, drops capabilities, uses a read-only root filesystem, and stores state in `/app/data`.

## Health and failure behavior

`GET /health` verifies app/database availability; it does not promise model readiness. `/api/status` reports configuration, not a successful inference probe. Run the local smoke script on the deployed machine to check Ollama and verify the embedding model separately with a source search. If the embedding model is unavailable, uploads remain searchable through the lexical fallback. A failed model job records a failure and accepts no fabricated result. Interrupted jobs are marked failed on startup and need explicit retry.

The queue accepts at most three jobs, serializes inference and limits each account's model requests. Long courses may hit the 15-minute timeout. Profile your actual course sizes and target hardware before increasing limits.

Telegram acknowledges updates before its in-process background work completes. Duplicate IDs are retained for seven days. A crash after acknowledgement can lose a reply; the student should resend their message. This pilot does **not** promise exactly-once delivery or a durable outbound queue. Limit Telegram to a small invited group until a durable worker/outbox is implemented. Never enable debug logging of framework HTTP requests, source text or webhook bodies.

## Backup and restore

Direct local deployment:

```bash
uv run python -m scripts.backup /private/backup/location/scopewise-2026-08-31.sqlite3
```

The helper uses SQLite's online backup API and verifies integrity. It refuses to overwrite an existing backup and creates it with mode 0600. Backups include documents, accounts and sessions: encrypt and restrict them. Do not commit them or leave them in public static directories.

Container deployment: create a backup within the private data volume and copy it to a private host directory:

```bash
docker compose exec app python -m scripts.backup /app/data/backup.sqlite3
docker compose cp app:/app/data/backup.sqlite3 /private/backup/location/backup.sqlite3
```

Use a new backup filename each time; remove temporary copies according to your retention policy.

To restore, first stop the app. Preserve the existing database and its `-wal`/`-shm` companions in a separate private recovery directory. Place the validated backup at the configured `scopewise.sqlite3` path, ensure UID 10001 owns container data, and set restrictive file permissions. A restored backup must not be combined with WAL files from a different database. Restart, sign in, inspect a source, build a sample pack, and verify ownership from a second account. Revoke restored sessions if old session access must not return. Perform a full restore rehearsal on the real host before launch; the automated backup test covers a temporary SQLite restore only.

Course deletion removes live records via foreign-key cascade. Existing exports, old backups and database free pages can retain data. Use disk encryption, a documented retention period, and appropriate secure disposal; do not claim forensic erasure.

## Release gates

- [ ] Evaluate real course material with a lecturer or student reviewer: objective omissions, incorrect links, ambiguous questions, diagram/text loss, and assessment-format judgments.
- [ ] Review and pin container/model versions and scan dependencies/images before public use.
- [ ] Verify TLS, secure cookie behavior, invitation handling and firewall boundaries on the actual host.
- [ ] Register the real Telegram webhook; verify linking, course selection, a tool call, a pack request and unlinking with a real private chat.
- [ ] Measure cold-start and typical/worst-case inference time, concurrent upload pressure, storage growth and rate limits.
- [ ] Rehearse backup/restore and establish retention plus an account recovery/admin process.
- [ ] Record the demo honestly, distinguishing fixture data from live model output.

No host, domain, paid service, real bot or public deployment is created by the repository setup scripts.
