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

LinkHosting does not manage DNS — you must add DNS records pointing each site's domain to your server's IP.

### Option A: dnsmasq (recommended for home/lab networks)

```bash
sudo apt-get install -y dnsmasq

# Add to /etc/dnsmasq.conf:
# address=/.local/192.168.1.100
# (Replace 192.168.1.100 with your host's LAN IP)
sudo systemctl restart dnsmasq
```

**Note**: `.local` conflicts with mDNS (Avahi/Bonjour). To avoid conflicts, use `.internal` or `.lan` as your `DOMAIN_SUFFIX` in `.env`.

### Option B: Pi-hole (existing Pi-hole)

Add custom DNS records via the Pi-hole admin panel:
- Domain: `mysite.local`
- IP: `<host LAN IP>`

### Option C: Manual /etc/hosts (per-client, for testing)

On each client machine, add to `/etc/hosts` (Linux/Mac) or `C:\Windows\System32\drivers\etc\hosts` (Windows):

```
192.168.1.100  mysite.local
192.168.1.100  myapp.local
```

---

## Working with Sites

### Create a site

```bash
./scripts/create-site.sh mysite static
./scripts/create-site.sh myapp node
./scripts/create-site.sh myapi python --domain myapi.internal
./scripts/create-site.sh myproxy proxy --upstream http://192.168.1.50:3000
```

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
# Block control-plane API from general LAN — admin only
sudo ufw allow from 192.168.1.10 to any port 8000  # Admin host only
sudo ufw enable
```

---

## Adding New Site Types

1. Add the new type to `SiteType` enum in `control-plane/app/models/__init__.py`
2. Add default Docker image in `control-plane/app/services/container.py`
3. Add port mapping in `control-plane/app/services/proxy.py`
4. Add a template in `site-templates/<type>.yml`
5. Run tests: `cd control-plane && python -m pytest tests/ -v`
