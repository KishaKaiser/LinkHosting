# LinkHosting — Operations Guide

## Prerequisites (Ubuntu 24.04)

```bash
# Install Docker
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Add your user to docker group (log out and back in after)
sudo usermod -aG docker $USER
```

---

## Initial Setup

### 1. Clone and configure

```bash
git clone https://github.com/KishaKaiser/LinkHosting.git
cd LinkHosting

# Copy environment template and fill in values
cp .env.example .env
nano .env    # Set strong passwords and secret key
```

### 2. Create data directories

```bash
sudo mkdir -p /data/sites /data/certs/ca /data/sftp /data/proxy/conf.d
sudo chown -R $USER:$USER /data
```

### 3. Start the stack

```bash
docker compose up -d --build

# Check status
docker compose ps
docker compose logs control-plane
```

### 4. Verify health

```bash
curl http://localhost:8000/health
# Expected: {"status":"ok","dev_mode":false}
```

---

## DNS Setup

LinkHosting includes a built-in **CoreDNS** service (`lh-dns`) that automatically creates `A` records for every deployed site (`sitename.link → HOST_LAN_IP`).  No manual `/etc/hosts` entries or external DNS tools are needed.

By default CoreDNS is exposed on host **port 5353** (not 53) to avoid conflicts with `systemd-resolved` on Ubuntu 24.04.  Standard DNS clients expect port 53, so choose one of the options below.

### Option A — query on port 5353 directly

No host changes required.  Works for any client that supports a custom DNS port:

```bash
dig mysite.link @192.168.4.32 -p 5353
nslookup -port=5353 mysite.link 192.168.4.32
```

For routers that support DNS-over-custom-port (rare), set the port to 5353 in the router's DNS settings.

### Option B (recommended) — enable the port-53 forwarder container

Start the optional `dns-forwarder` service.  It listens on host port 53 and proxies all queries to `lh-dns`, so standard DNS clients need no special configuration:

```bash
# Prerequisites: nothing using port 53 on the host (check with: sudo ss -ulnp | grep :53)
docker compose --profile dns-forwarder up -d
```

Then configure your router's DHCP to hand out `192.168.4.32` as the primary DNS server.  All LAN devices will resolve `*.link` automatically without any per-device changes.

Verify:
```bash
dig mysite.link @192.168.4.32          # standard port 53
```

### Option C — move CoreDNS itself to port 53

Disable `systemd-resolved`, then set `DNS_PORT=53` in `.env` and restart:

```bash
sudo systemctl disable --now systemd-resolved
sudo rm /etc/resolv.conf
echo "nameserver 1.1.1.1" | sudo tee /etc/resolv.conf

# In .env:  DNS_PORT=53
docker compose up -d
```

Verify:
```bash
dig mysite.link @192.168.4.32
```

### Troubleshooting DNS

```bash
# Check CoreDNS is running
docker compose ps dns

# View CoreDNS logs
docker compose logs dns

# Check the hosts file CoreDNS reads
docker compose exec panel cat /data/dns/hosts

# Test port reachability (default port 5353)
nc -zu 192.168.4.32 5353

# Test port reachability (if dns-forwarder or DNS_PORT=53)
nc -zu 192.168.4.32 53
```

If `dig` returns NXDOMAIN: the site may not be deployed yet, or `HOST_LAN_IP` is not set in `.env`, or `DNS_ENABLED=false`.

---

## Working with Sites

### Create a site

```bash
./scripts/create-site.sh mysite static
./scripts/create-site.sh myapp node
./scripts/create-site.sh myapi python --domain myapi.link
./scripts/create-site.sh myproxy proxy --upstream http://192.168.4.50:3000
```

### Import a GitHub repository

A site can be populated with code from any **public** GitHub repository.

**At creation time** (type is auto-detected from repo contents):

```bash
# site_type is inferred: package.json→node, requirements.txt→python, *.php→php, else→static
curl -s -X POST http://localhost:8000/sites \
  -H "Content-Type: application/json" \
  -d '{"name":"myapp","github_repo":"https://github.com/owner/myapp"}' | python3 -m json.tool
```

**After creation** (re-import or switch repos):

```bash
curl -s -X POST http://localhost:8000/sites/myapp/import-github \
  -H "Content-Type: application/json" \
  -d '{"repo_url":"https://github.com/owner/myapp","branch":"main"}' | python3 -m json.tool
```

Both calls clone the repo into `/data/sites/<name>/` and record `git_repo` + `git_branch` on the site.

### Deploy a site (provision container + vhost)

```bash
./scripts/deploy-site.sh mysite
```

Upload files via SFTP to `/data/sites/mysite/` after deploying.

### Issue a TLS certificate

```bash
./scripts/create-cert.sh mysite
```

This issues a cert signed by the internal CA and configures HTTPS on the proxy.

### Create a database

```bash
./scripts/create-db.sh mysite postgres
# Returns credentials — save the password securely!
```

### Create SFTP access

```bash
./scripts/create-sftp.sh mysite
# Returns connection details and password (shown once)
# Connect with:
sftp -P 2222 sftp-mysite@<host-ip>
```

---

## Development Mode

Run without Docker or root privileges:

```bash
# Install Python dependencies
cd control-plane
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Set dev mode
export DEV_MODE=true
export DATABASE_URL=sqlite:///./dev.db
export ADMIN_SECRET_KEY=dev-key

# Run the API
uvicorn app.main:app --reload --port 8000
```

Or use Docker Compose in dev mode:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

---

## Running Tests

```bash
cd control-plane
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

---

## Upgrading

```bash
git pull
docker compose build
docker compose up -d
```

---

## Backup

```bash
# Back up control-plane database
docker exec lh-db pg_dump -U linkhosting linkhosting > backup-$(date +%Y%m%d).sql

# Back up CA key (CRITICAL — store offline)
cp /data/certs/ca/ca.key /secure/offline/location/

# Back up all site files
tar czf sites-$(date +%Y%m%d).tar.gz /data/sites/
```

---

## Firewall (ufw)

```bash
sudo ufw allow ssh        # Keep SSH access!
sudo ufw allow 80/tcp     # HTTP
sudo ufw allow 443/tcp    # HTTPS
sudo ufw allow 2222/tcp   # SFTP
# DNS (default port 5353; change to 53 if using dns-forwarder or DNS_PORT=53)
sudo ufw allow 5353/udp   # CoreDNS (default)
sudo ufw allow 5353/tcp   # CoreDNS (default)
# sudo ufw allow 53/udp   # Uncomment if using port 53 (dns-forwarder or DNS_PORT=53)
# sudo ufw allow 53/tcp   # Uncomment if using port 53
# Block control-plane API from general LAN — admin only
sudo ufw allow from 192.168.4.0/24 to any port 8000  # LAN only — tighten to admin host if needed
sudo ufw enable
```

---

## Adding New Site Types

1. Add the new type to `SiteType` enum in `control-plane/app/models/__init__.py`
2. Add default Docker image in `control-plane/app/services/container.py`
3. Add port mapping in `control-plane/app/services/proxy.py`
4. Add a template in `site-templates/<type>.yml`
5. Run tests: `cd control-plane && python -m pytest tests/ -v`
