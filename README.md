# LinkHosting

**Internal-only multi-tenant web hosting control panel for Ubuntu 24.04.**

Provision and manage multiple isolated websites on a single server via a **web-based control panel** — each site reachable via a custom internal domain, with its own container/compose stack, Nginx reverse proxy config, TLS certificate, database, and SFTP access.

---

## Features

| Feature | Details |
|---------|---------|
| **Web Control Panel** | Browser UI at `/panel/` — login, dashboard, create sites, deploy, view logs |
| **Site types** | Static, PHP, Node.js, Python, Reverse Proxy, **WordPress** |
| **WordPress (one-click)** | Per-site docker-compose with WordPress + MariaDB, unique credentials |
| **Background Jobs** | Redis + RQ worker for async WordPress deployments |
| **Isolation** | Per-site Docker container or docker-compose project |
| **Internal domains** | `sitename.link` (configurable suffix) |
| **Built-in DNS** | CoreDNS serves `sitename.link` records automatically; clients point to this server |
| **Nginx proxy** | Auto-generated per-site vhost configs; nginx reloaded on deploy |
| **GitHub import** | Clone any public GitHub repo; site type auto-detected |
| **TLS** | Internal CA — self-signed root, signed site certs |
| **Databases** | Per-site PostgreSQL |
| **SFTP** | Per-site chroot SFTP accounts |
| **REST API** | Swagger UI at `/docs` |
| **Dev mode** | Run without Docker/root for local testing |

---

## Stack

| Service | Role |
|---------|------|
| `panel` | FastAPI app — serves web UI (`/panel/`) + REST API (`/docs`) |
| `worker` | RQ worker — executes async WordPress deploy jobs |
| `redis` | Job queue backend |
| `proxy` | Nginx reverse proxy — routes domains to per-site containers |
| `dns` | CoreDNS — resolves `*.link` names to the host LAN IP for LAN clients |
| `db` | PostgreSQL — control-plane data |
| `db-pg` | PostgreSQL — per-site databases |
| `sftp-server` | OpenSSH SFTP server |

---

## Quick Install (one command)

Clone the repo, then run the bootstrap installer for your platform.

**macOS / Linux**

```bash
git clone https://github.com/KishaKaiser/LinkHosting.git && cd LinkHosting
bash scripts/install.sh
```

Or, if you prefer a fully non-interactive install with all defaults accepted:

```bash
bash scripts/install.sh --non-interactive
```

To also register LinkHosting as a **systemd service** that auto-starts on boot (Linux):

```bash
bash scripts/install.sh --service
```

**Windows (PowerShell — run as Administrator)**

```powershell
git clone https://github.com/KishaKaiser/LinkHosting.git; cd LinkHosting
.\scripts\install.ps1
```

Non-interactive / silent install:

```powershell
.\scripts\install.ps1 -NonInteractive
```

The installer will:
1. Check prerequisites (Docker, docker compose, OpenSSL, curl, git)
2. Copy `.env.example` → `.env` and generate strong random secrets
3. Prompt for optional settings (domain suffix, bind address, SFTP port, **host LAN IP for DNS**)
4. Start the Docker Compose stack (`docker compose up -d --build`)
5. Wait for the API health check and print a post-install summary

---

## Quick Start (manual)

### 1. Prerequisites

```bash
# Install Docker (Ubuntu 24.04)
sudo apt-get update && sudo apt-get install -y docker-ce docker-compose-plugin
sudo usermod -aG docker $USER && newgrp docker
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — set strong passwords for DB_PASSWORD, SITE_DB_PASSWORD, ADMIN_SECRET_KEY
# Also set HOST_LAN_IP to the LAN IP of this server (e.g. 192.168.4.32)
nano .env
```

### 3. Start the stack

```bash
docker compose up -d --build
curl http://localhost:8000/health   # → {"status":"ok"}
```

Open the **web control panel** at: **http://localhost:8000/panel/**

Log in with the password set in `ADMIN_SECRET_KEY`.

### 4. Deploy your first WordPress site (one-click via panel)

1. Open **http://localhost:8000/panel/**
2. Click **New Site**
3. Fill in a name (e.g. `myblog`), select **WordPress**, click Create
4. On the site detail page, click **🚀 Deploy**
5. The deploy job is queued and the `worker` service handles it asynchronously.
   Refresh the page to see job status. Once `succeeded`, the site is live at `http://myblog.link`.

Visit `http://myblog.link` to see your WordPress installation.

### 5. Deploy other site types (CLI / API)

```bash
# The Python CLI tool reads ADMIN_SECRET_KEY from .env automatically.
# All commands below can also be run as the equivalent .sh wrapper.

# Create a static site
python3 scripts/lh.py create-site mysite static

# Or create a site by importing a GitHub repository (type auto-detected)
python3 scripts/lh.py create-site myapp node --github https://github.com/owner/myapp

# Deploy it (starts Docker container + writes Nginx vhost)
python3 scripts/lh.py deploy mysite

# Issue TLS certificate
python3 scripts/lh.py cert mysite

# Create a database
python3 scripts/lh.py create-db mysite postgres    # ← save the password!

# Create SFTP access
python3 scripts/lh.py create-sftp mysite           # ← save the password!

# Legacy .sh wrappers (delegate to lh.py):
./scripts/create-site.sh mysite static
./scripts/deploy-site.sh mysite
./scripts/create-cert.sh mysite
./scripts/create-db.sh mysite postgres
./scripts/create-sftp.sh mysite
```

### 6. Configure clients to use the built-in DNS server

LinkHosting runs a **CoreDNS** service that automatically creates a DNS record for every deployed site (`sitename.link → HOST_LAN_IP`).  No manual `/etc/hosts` entries are needed.

CoreDNS is exposed on host **port 5353** by default (`DNS_PORT=5353`) to avoid conflicts with `systemd-resolved`.  Standard DNS clients expect port 53, so pick one of the options below.

**Option A — query on port 5353 directly (no host changes needed):**
Use `dig` or `nslookup` with an explicit port.  Useful for testing or for routers/clients that support custom DNS ports:
```bash
dig mysite.link @192.168.4.32 -p 5353
```

**Option B (recommended for LAN clients) — enable the port-53 forwarder container:**
Start the optional `dns-forwarder` service.  It listens on host port 53 and proxies all queries to the CoreDNS container, so standard clients can point to this server without any custom-port configuration:
```bash
docker compose --profile dns-forwarder up -d
```
Then configure your router's DHCP to hand out `192.168.4.32` as the primary DNS server.  All LAN devices will resolve `*.link` automatically.

**Option C — move CoreDNS itself to port 53:**
Disable `systemd-resolved` first, then set `DNS_PORT=53` in `.env` and restart the stack:
```bash
sudo systemctl disable --now systemd-resolved
sudo rm /etc/resolv.conf
echo "nameserver 1.1.1.1" | sudo tee /etc/resolv.conf
# In .env: DNS_PORT=53
docker compose up -d
```

**Verify DNS is working:**

By default CoreDNS is exposed on host **port 5353** (not 53) to avoid conflicts with `systemd-resolved` on Ubuntu 24.04.  Use the `-p` flag when querying directly:

```bash
# Replace 192.168.4.32 with your actual server LAN IP
dig mysite.link @192.168.4.32 -p 5353          # should return your server's LAN IP
nslookup -port=5353 mysite.link 192.168.4.32   # alternative

# If you set DNS_PORT=53 in .env (or enabled the dns-forwarder profile), omit the port flag:
dig mysite.link @192.168.4.32
```

For standard clients that cannot specify a custom port, see **[Step 6 — DNS client setup](#6-configure-clients-to-use-the-built-in-dns-server)** options below.

**Troubleshooting:**
- If `dig` returns NXDOMAIN, the site may not have been deployed yet, or `HOST_LAN_IP` is not set in `.env`.
- Check CoreDNS logs: `docker compose logs dns`
- Check port 5353 is reachable: `nc -zu <server-lan-ip> 5353`
- Confirm the hosts file is populated: `docker compose exec panel cat /data/dns/hosts`
- If `DNS_ENABLED=false` in `.env`, DNS records are not managed automatically.

### 7. Trust the CA

```bash
curl http://localhost:8000/ca.crt -o linkhosting-ca.crt
sudo cp linkhosting-ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

See [docs/ca-trust.md](docs/ca-trust.md) for other platforms (macOS, Windows, Firefox).

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_PASSWORD` | ✅ | — | PostgreSQL password for control-plane DB |
| `SITE_DB_PASSWORD` | ✅ | — | PostgreSQL password for site databases |
| `ADMIN_SECRET_KEY` | ✅ | — | Panel login password + API Bearer token |
| `SESSION_SECRET_KEY` | ✅ | — | Secret for signing session cookies |
| `DOMAIN_SUFFIX` | | `link` | Suffix for auto-generated site domains |
| `PANEL_PORT` | | `127.0.0.1:8000` | Host:port to expose the panel on |
| `SFTP_PORT` | | `2222` | Host port for SFTP server |
| `DEV_MODE` | | `false` | Skip real Docker calls (for local dev) |
| `DNS_ENABLED` | | `true` | Enable built-in CoreDNS and auto DNS record management |
| `HOST_LAN_IP` | | — | Server LAN IP; A records for `sitename.link` resolve here |
| `DNS_LISTEN_ADDR` | | `0.0.0.0` | Address CoreDNS binds port 53 on |
| `DNS_PORT` | | `5353` | Host port CoreDNS is exposed on (use 53 if systemd-resolved is disabled) |

---

## WordPress Deployment Flow

1. User creates a site of type `wordpress` via the panel or API
2. User clicks **Deploy** → a `DeployJob` row is created (status: `queued`)
3. The job is pushed to the `deploy` Redis queue
4. The `worker` container picks it up and:
   - Creates `/srv/linkhosting/sites/<name>/docker-compose.yml` with `wordpress` + `mariadb` services
   - Generates unique random credentials and writes them to `/srv/linkhosting/sites/<name>/.secrets`
   - Runs `docker compose -f ... -p lh_wp_<name> up -d --remove-orphans`
   - Writes an Nginx vhost config and reloads Nginx
5. Job status is updated to `succeeded` or `failed` with captured stdout/stderr logs
6. Panel UI shows the job status and logs on the site detail page

---

## Development Mode

Run without Docker or root:

```bash
cd control-plane
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DEV_MODE=true DATABASE_URL=sqlite:///./dev.db ADMIN_SECRET_KEY=dev SESSION_SECRET_KEY=dev-session
uvicorn app.main:app --reload --port 8000
# Browse control panel at http://localhost:8000/panel/
# Browse API docs at http://localhost:8000/docs
```

In dev mode, WordPress deployments run inline (no real `docker compose` calls) so you can test the full flow without a live Docker environment.

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
| `/sites/{name}/deploy` | POST | Deploy site (async job for WordPress) |
| `/sites/{name}/stop` | POST | Stop site |
| `/sites/{name}/jobs` | GET | List deploy jobs for a site |
| `/sites/{name}/import-github` | POST | Clone/re-clone a GitHub repo |
| `/sites/{name}/cert` | POST | Issue TLS certificate |
| `/sites/{name}/cert` | GET | List certificates |
| `/sites/{name}/database` | POST | Create database |
| `/sites/{name}/database` | GET | List databases |
| `/sites/{name}/sftp` | POST | Create SFTP account |
| `/sites/{name}/sftp` | GET | List SFTP accounts |
| `/jobs` | GET | List all deploy jobs |
| `/jobs/{id}` | GET | Get deploy job details + logs |
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

## Technology Stack

- **Panel / API**: Python 3.12 + FastAPI + Jinja2 + SQLAlchemy
- **Background Jobs**: Redis + RQ
- **Control-plane DB**: PostgreSQL 16
- **WordPress**: docker-compose per site (WordPress + MariaDB)
- **Proxy**: Nginx 1.27 (auto-configured per site)
- **SFTP**: OpenSSH
- **TLS**: Python `cryptography` library (internal CA)

---

## License

MIT
