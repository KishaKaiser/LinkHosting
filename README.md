# LinkHosting

**Internal-only multi-tenant web hosting control plane for Ubuntu 24.04.**

Provision and manage multiple isolated websites on a single server — each reachable via a custom internal domain (e.g. `https://mysite.local`), with its own container, TLS certificate, database, and SFTP access.

---

## Features

| Feature | Details |
|---------|---------|
| **Site types** | Static, PHP, Node.js, Python, Reverse Proxy |
| **Isolation** | One Docker container per site |
| **Internal domains** | `sitename.local` (configurable suffix) |
| **TLS** | Internal CA — self-signed root, signed site certs |
| **Databases** | Per-site PostgreSQL (MySQL coming soon) |
| **SFTP** | Per-site chroot SFTP accounts |
| **Admin API** | REST API + Swagger UI at `/docs` |
| **Dev mode** | Run without Docker/root for local testing |

---

## Quick Start (Ubuntu 24.04)

### 1. Prerequisites

```bash
# Install Docker
sudo apt-get update && sudo apt-get install -y docker-ce docker-compose-plugin
sudo usermod -aG docker $USER && newgrp docker

# Create data directories
sudo mkdir -p /data/sites /data/certs/ca /data/sftp /data/proxy/conf.d
sudo chown -R $USER:$USER /data
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — set strong passwords for DB_PASSWORD, SITE_DB_PASSWORD, ADMIN_SECRET_KEY
nano .env
```

### 3. Start the stack

```bash
docker compose up -d --build
curl http://localhost:8000/health   # → {"status":"ok"}
```

### 4. Create your first site

```bash
# Create a static site
./scripts/create-site.sh mysite static

# Deploy it (starts Docker container + writes Nginx vhost)
./scripts/deploy-site.sh mysite

# Issue TLS certificate
./scripts/create-cert.sh mysite

# Create a database
./scripts/create-db.sh mysite postgres    # ← save the password!

# Create SFTP access
./scripts/create-sftp.sh mysite           # ← save the password!
```

### 5. Add DNS

Add an A record pointing `mysite.local` to your host's LAN IP, or add to `/etc/hosts`:

```
192.168.1.100  mysite.local
```

### 6. Trust the CA

```bash
curl http://localhost:8000/ca.crt -o linkhosting-ca.crt
sudo cp linkhosting-ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

See [docs/ca-trust.md](docs/ca-trust.md) for other platforms (macOS, Windows, Firefox).

---

## Development Mode

Run without Docker or root:

```bash
cd control-plane
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DEV_MODE=true DATABASE_URL=sqlite:///./dev.db ADMIN_SECRET_KEY=dev
uvicorn app.main:app --reload --port 8000
# Browse API docs at http://localhost:8000/docs
```

---

## API Reference

Full interactive API docs available at `http://localhost:8000/docs` when running.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/sites` | GET | List all sites |
| `/sites` | POST | Create a site |
| `/sites/{name}` | GET | Get site details |
| `/sites/{name}` | PATCH | Update site |
| `/sites/{name}` | DELETE | Delete site + container |
| `/sites/{name}/deploy` | POST | Provision container + vhost |
| `/sites/{name}/stop` | POST | Stop container |
| `/sites/{name}/cert` | POST | Issue TLS certificate |
| `/sites/{name}/cert` | GET | List certificates |
| `/sites/{name}/database` | POST | Create database |
| `/sites/{name}/database` | GET | List databases |
| `/sites/{name}/sftp` | POST | Create SFTP account |
| `/sites/{name}/sftp` | GET | List SFTP accounts |
| `/ca.crt` | GET | Download internal CA certificate |
| `/health` | GET | Health check |

---

## Testing

```bash
cd control-plane
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [docs/architecture.md](docs/architecture.md) | System architecture and component details |
| [docs/threat-model.md](docs/threat-model.md) | Threat model and security mitigations |
| [docs/operations.md](docs/operations.md) | Setup, operations, backup, firewall |
| [docs/ca-trust.md](docs/ca-trust.md) | How to trust the internal CA on client machines |
| [site-templates/README.md](site-templates/README.md) | Site type templates |

---

## Stack

- **Control Plane**: Python 3.12 + FastAPI + SQLAlchemy
- **Database**: PostgreSQL 16
- **Proxy**: Nginx 1.27
- **SFTP**: OpenSSH (Ubuntu 24.04)
- **Containers**: Docker
- **TLS**: Python `cryptography` library (internal CA)

---

## License

MIT
