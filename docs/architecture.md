# LinkHosting — Architecture

## Overview

LinkHosting is an **internal-only multi-tenant web hosting control plane** for Ubuntu 24.04.
It provisions isolated Docker containers per site, routes traffic via Nginx, manages TLS certificates using an internal CA, and creates per-site databases and SFTP accounts.

## System Components

```
                    ┌──────────────────────────────────────────────────────┐
                    │                   Ubuntu 24.04 Host                  │
                    │                                                       │
  Internal LAN ─────┤──► Nginx Reverse Proxy (:80/:443)                   │
                    │         │                                            │
                    │         │  proxy_pass to container                  │
                    │         ▼                                            │
                    │   ┌──────────────┐  ┌──────────────┐               │
                    │   │ site-myapp   │  │ site-mysite  │  ...          │
                    │   │ (node:20)    │  │ (nginx:alpine│               │
                    │   └──────────────┘  └──────────────┘               │
                    │                                                       │
                    │   Control Plane API (FastAPI :8000) ◄─── Admin      │
                    │         │                                            │
                    │         ├── PostgreSQL (control-plane DB)            │
                    │         ├── PostgreSQL (site databases)              │
                    │         ├── SFTP Server (:2222)                      │
                    │         └── Internal CA (cert generation)            │
                    └──────────────────────────────────────────────────────┘
```

## Component Details

### Control Plane API (`control-plane/`)
- **Language**: Python 3.12 + FastAPI
- **Database**: SQLAlchemy ORM + PostgreSQL
- **Responsibilities**:
  - Site CRUD (name, type, domain, container image)
  - Container provisioning via Docker SDK
  - TLS cert issuance via internal CA (cryptography library)
  - Database creation (PostgreSQL per-site)
  - SFTP account management
  - Nginx vhost config generation
- **Endpoints**: See [API docs](http://localhost:8000/docs) when running

### Nginx Reverse Proxy (`proxy/`)
- Single Nginx instance on the host
- Reads per-site vhost configs from `/data/proxy/conf.d/`
- Each site config routes `sitename.local` → `http://site-<name>:<port>`
- TLS termination using certs from `/data/certs/<sitename>/`

### Internal CA
- Implemented using Python `cryptography` library
- Root CA key + cert stored in `/data/certs/ca/`
- Issues site-specific certs (2-year validity) signed by the root CA
- Clients must trust the root CA (see [ca-trust.md](ca-trust.md))

### SFTP Server (`sftp-server/`)
- Ubuntu 24.04 + OpenSSH `internal-sftp`
- Per-site chroot directories under `/data/sftp/<username>/`
- User accounts managed via `/data/sftp/users.conf`
- Exposed on host port 2222

### Site Containers
- One Docker container per site
- Supported types: `static`, `php`, `node`, `python`, `proxy`
- All containers join a shared `linkhosting_sites` Docker network
- The Nginx proxy communicates with containers via container name (`site-<name>`)

### Databases
- Shared PostgreSQL instance (`db-pg`) for site databases
- Each site gets its own database + user with a randomly generated password
- Credentials returned once at creation time

## Data Flows

### Site Creation
```
Client → POST /sites
  → Control Plane creates Site record in DB
  → Returns site metadata (status: pending)
```

### Site Deployment
```
Client → POST /sites/<name>/deploy
  → Control Plane calls Docker SDK to create container
  → Writes Nginx vhost config to /data/proxy/conf.d/<name>.conf
  → Signals Nginx to reload
  → Returns site metadata (status: running)
```

### TLS Cert Issuance
```
Client → POST /sites/<name>/cert
  → Control Plane generates RSA key + CSR
  → Signs with internal CA key
  → Writes cert+chain to /data/certs/<name>/cert.pem
  → Updates Nginx vhost to TLS
  → Signals Nginx to reload
```

## Networking

- All site traffic is **internal-only** — the host firewall should block external access
- The `backend` Docker network is internal (no external routing)
- The `sites` Docker network connects proxy to site containers
- The proxy is the only container exposed on LAN ports 80/443

## Storage Layout

```
/data/
  sites/
    <sitename>/          # Site files (mounted at /var/www/html in container)
  certs/
    ca/
      ca.key             # Internal CA private key (root secret — protect!)
      ca.crt             # Internal CA certificate (distribute to clients)
    <sitename>/
      cert.pem           # Site TLS certificate + CA chain
      key.pem            # Site TLS private key
  sftp/
    users.conf           # SFTP user accounts
    <username>/          # SFTP chroot per user
      www/               # Writable upload directory
  proxy/
    conf.d/              # Nginx vhost configs (auto-generated)
```

## Development Mode

Set `DEV_MODE=true` to run the control plane without real Docker/system calls.
In dev mode:
- Container provisioning is simulated
- Cert generation writes placeholder files
- Proxy config is written to the configured path but Nginx reload is skipped
- Database provisioning is skipped (only SQLite for control plane)

See [operations.md](operations.md) for setup instructions.
