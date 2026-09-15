# Deployment

## Docker Compose (recommended)

The standard deployment path. Bundles FastAPI backend, Svelte frontend, and context-link binary into a single container.

```bash
git clone https://github.com/theAstiv/paranoid && cd paranoid
cp .env.example .env          # edit with your API key
docker compose up --build
```

**First build**: ~5–10 min (Go toolchain + Node modules + Python deps + fastembed model pre-bake).  
**Subsequent builds**: fast — Docker caches each layer.

**Access:**
- Web UI: `http://localhost:8000/app`
- API docs: `http://localhost:8000/docs`

### Build arguments

```bash
# Pin context-link version
CONTEXT_LINK_VERSION=1.0.0 docker compose build

# Use a larger embedding model
EMBEDDING_MODEL=BAAI/bge-base-en-v1.5 docker compose build
```

### Offline build (no Go toolchain or GitHub access)

1. Comment out the `context-link-builder` stage in `Dockerfile`.
2. Remove the `COPY --from=context-link-builder` line in the `final` stage.
3. Mount a pre-built binary at runtime:

```yaml
# docker-compose.yml
volumes:
  - ./data:/app/data
  - /path/to/context-link:/app/bin/context-link:ro
```

The `--code` flag logs a warning and continues without code context if the binary is absent.

### Container security hardening

The default `docker-compose.yml` applies:

| Setting | Value | Effect |
|---------|-------|--------|
| `cap_drop` | `ALL` | Drops every Linux capability |
| `security_opt` | `no-new-privileges:true` | Blocks privilege escalation |
| Port binding | `127.0.0.1:8000:8000` | Loopback-only by default |
| Runtime user | `app` (uid 1000) | Non-root |

For LAN or public exposure, change the port binding in `docker-compose.yml`:

```yaml
ports:
  - "0.0.0.0:8000:8000"
```

And set `ALLOWED_ORIGINS` to your public origin for CSRF protection:

```bash
ALLOWED_ORIGINS=https://paranoid.yourcompany.com
```

### Persistent data

SQLite is stored at `/app/data/paranoid.db` inside the container, bind-mounted to `./data/` on the host. This survives container restarts and image upgrades.

---

## PyPI (CLI only)

```bash
pip install paranoid-cli
paranoid config init
paranoid run system.md
```

Requires Python 3.12+. The CLI connects to a remote Paranoid server or uses the local SQLite database at `~/.paranoid/paranoid.db`.

---

## Standalone binary (no Python required)

Download from [GitHub Releases](https://github.com/theAstiv/paranoid/releases/latest):

```bash
# Linux/macOS
chmod +x paranoid-linux-x64
./paranoid-linux-x64 config init

# macOS — if Gatekeeper blocks it
xattr -d com.apple.quarantine paranoid-macos-arm64

# Windows — if SmartScreen blocks it
# Click "More info" → "Run anyway"
```

---

## From source (development)

```bash
git clone https://github.com/theAstiv/paranoid && cd paranoid

# Backend
pip install -e ".[dev]"
uvicorn backend.main:app --reload

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

Frontend dev server: `http://localhost:5173`  
Backend: `http://localhost:8000`

---

## Production hardening checklist

- [ ] Set `PARANOID_REQUIRE_AUTH=true`
- [ ] Set `PARANOID_ADMIN_PASSWORD` to a strong passphrase
- [ ] Set `JWT_SECRET` to a random 32+ char string
- [ ] Set `CONFIG_SECRET` to protect the Settings page and encrypt PATs
- [ ] Set `ALLOWED_ORIGINS` to your concrete public origin(s)
- [ ] Put the container behind a TLS-terminating reverse proxy (nginx, Caddy, Traefik)
- [ ] Set `CORS_ORIGINS` to your frontend origin(s)
- [ ] Bind the port to `0.0.0.0` only if needed; prefer a reverse proxy instead
- [ ] Mount `./data` as a named volume with regular backups
- [ ] Pin `CONTEXT_LINK_VERSION` to a specific release in `docker-compose.yml`

### Example nginx reverse proxy

```nginx
server {
    listen 443 ssl;
    server_name paranoid.yourcompany.com;

    ssl_certificate     /etc/ssl/certs/paranoid.crt;
    ssl_certificate_key /etc/ssl/private/paranoid.key;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        # Required for SSE (pipeline progress events)
        proxy_buffering    off;
        proxy_cache        off;
        proxy_read_timeout 600s;
    }
}
```

---

## Platform support

| Platform | PyPI | Docker | Binary |
|----------|------|--------|--------|
| Ubuntu 20.04+ | ✓ | ✓ | ✓ |
| Debian 11+ | ✓ | ✓ | ✓ |
| RHEL 8+ | ✓ | ✓ | ✓ |
| macOS 11+ (Intel) | ✓ | ✓ | — |
| macOS 11+ (ARM64) | ✓ | ✓ | ✓ |
| Windows 10+ | ✓ | ✓ | ✓ |
| WSL2 | ✓ | ✓ | ✓ |

---

## Using the CLI inside the container

```bash
# Run against a file already in the container
docker compose exec app paranoid run /app/examples/stride-example-api-gateway.md

# Mount a local file and run it
docker run --rm \
  -v $(pwd)/my-system.md:/workspace/system.md \
  -v $(pwd)/data:/app/data \
  -e ANTHROPIC_API_KEY=sk-ant-xxx \
  paranoid-app-1 \
  paranoid run /workspace/system.md --format markdown -o /app/data/report.md
```
