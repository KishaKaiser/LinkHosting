#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# LinkHosting Bootstrap Installer  (macOS / Linux)
#
# Usage (remote):
#   curl -fsSL https://raw.githubusercontent.com/KishaKaiser/LinkHosting/main/scripts/install.sh | bash
#
# Usage (local):
#   ./scripts/install.sh [--non-interactive] [--service] [--help]
#
# Options:
#   --non-interactive / -y   Accept all defaults without prompting
#   --service                Install as a systemd service (Linux only)
#   --help / -h              Show this help message
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
info()  { echo -e "${CYAN}[INFO]${RESET}  $*"; }
ok()    { echo -e "${GREEN}[ OK ]${RESET}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
die()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }

# ── Banner ────────────────────────────────────────────────────────────────────
echo -e "${BOLD}"
cat <<'BANNER'
  _     _       _    _   _           _   _
 | |   (_)_ __ | | _| | | | ___  ___| |_(_)_ __   __ _
 | |   | | '_ \| |/ / |_| |/ _ \/ __| __| | '_ \ / _` |
 | |___| | | | |   <|  _  | (_) \__ \ |_| | | | | (_| |
 |_____|_|_| |_|_|\_\_| |_|\___/|___/\__|_|_| |_|\__, |
                                                  |___/
BANNER
echo -e "${RESET}${BOLD}Bootstrap Installer — macOS / Linux${RESET}"
echo "────────────────────────────────────────────────────────────────"

# ── Argument parsing ──────────────────────────────────────────────────────────
NON_INTERACTIVE=false
INSTALL_SERVICE=false
for arg in "$@"; do
  case "$arg" in
    --non-interactive|-y) NON_INTERACTIVE=true ;;
    --service)            INSTALL_SERVICE=true ;;
    --help|-h)
      sed -n '3,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) die "Unknown option: $arg  (use --help for usage)" ;;
  esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────

# prompt <var_name> <display_text> <default>
prompt() {
  local var_name="$1" prompt_text="$2" default_val="$3"
  if [[ "$NON_INTERACTIVE" == "true" ]]; then
    eval "${var_name}=\"\${default_val}\""
    return
  fi
  read -r -p "${prompt_text} [${default_val}]: " _input
  eval "${var_name}=\"\${_input:-\${default_val}}\""
}

# check_cmd <binary> <label> [install_hint]
check_cmd() {
  local cmd="$1" label="${2:-$1}" hint="${3:-}"
  if command -v "$cmd" &>/dev/null; then
    ok "$label → $(command -v "$cmd")"
    return 0
  else
    echo -e "${RED}[MISS]${RESET}  $label not found.${hint:+  $hint}" >&2
    return 1
  fi
}

# set_env <KEY> <value>  — upsert a key=value line in .env
set_env() {
  local key="$1" value="$2"
  # Escape characters that are special in the sed replacement string
  local esc
  esc="$(printf '%s\n' "$value" | sed 's/[\/&]/\\&/g')"
  if grep -q "^${key}=" "$REPO_ROOT/.env" 2>/dev/null; then
    sed -i.bak "s|^${key}=.*|${key}=${esc}|" "$REPO_ROOT/.env"
  else
    echo "${key}=${value}" >> "$REPO_ROOT/.env"
  fi
  rm -f "$REPO_ROOT/.env.bak"
}

# ── Detect OS ─────────────────────────────────────────────────────────────────
OS="$(uname -s)"
case "$OS" in
  Linux*)  PLATFORM=linux ;;
  Darwin*) PLATFORM=macos ;;
  *)       die "Unsupported OS: $OS.  Use scripts/install.ps1 on Windows." ;;
esac
info "Platform: $PLATFORM"

# ── Locate repo root ──────────────────────────────────────────────────────────
# Works whether the script is executed directly or piped through bash.
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
else
  # Piped via curl — assume the working directory is the repo root
  REPO_ROOT="$(pwd)"
fi
info "Repo root: $REPO_ROOT"
cd "$REPO_ROOT"

# ── Dependency installers ─────────────────────────────────────────────────────

install_docker_linux() {
  info "Docker not found — installing Docker Engine via get.docker.com…"
  warn "The official Docker install script will be downloaded and executed as root."
  warn "Review it at https://get.docker.com before proceeding."
  if ! command -v curl &>/dev/null && ! command -v wget &>/dev/null; then
    die "Neither curl nor wget is available. Install one and re-run."
  fi
  if command -v curl &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
  else
    wget -qO- https://get.docker.com | sh
  fi
  # Add current user to the docker group so non-root use works after re-login
  if ! id -nG "$USER" 2>/dev/null | grep -qw 'docker'; then
    sudo usermod -aG docker "$USER" 2>/dev/null || true
    warn "Added $USER to the 'docker' group. You may need to log out and back in."
  fi
  # Start and enable the Docker daemon
  if command -v systemctl &>/dev/null; then
    sudo systemctl enable --now docker 2>/dev/null || true
  fi
  ok "Docker Engine installed."
}

install_docker_macos() {
  if command -v brew &>/dev/null; then
    info "Docker not found — installing Docker Desktop via Homebrew…"
    brew install --cask docker
    ok "Docker Desktop installed. Please open Docker.app to finish setup."
    warn "Re-run this installer once the Docker daemon is running."
    exit 0
  else
    die "Docker not found and Homebrew is not available.\n" \
        "  Install Docker Desktop from https://docs.docker.com/desktop/install/mac-install/\n" \
        "  then re-run this installer."
  fi
}

install_openssl_linux() {
  info "OpenSSL not found — attempting to install…"
  if command -v apt-get &>/dev/null; then
    sudo apt-get install -y openssl
  elif command -v yum &>/dev/null; then
    sudo yum install -y openssl
  elif command -v dnf &>/dev/null; then
    sudo dnf install -y openssl
  elif command -v apk &>/dev/null; then
    sudo apk add --no-cache openssl
  else
    die "Cannot install OpenSSL automatically. Install it via your package manager and re-run."
  fi
  ok "OpenSSL installed."
}

install_curl_linux() {
  info "curl not found — attempting to install…"
  if command -v apt-get &>/dev/null; then
    sudo apt-get install -y curl
  elif command -v yum &>/dev/null; then
    sudo yum install -y curl
  elif command -v dnf &>/dev/null; then
    sudo dnf install -y curl
  elif command -v apk &>/dev/null; then
    sudo apk add --no-cache curl
  else
    warn "Cannot install curl automatically. Skipping post-install health check."
  fi
}

# ── Check / install prerequisites ────────────────────────────────────────────
echo ""
info "Checking prerequisites…"
PREREQ_OK=true

# Docker engine
if ! command -v docker &>/dev/null; then
  if [[ "$PLATFORM" == "linux" ]]; then
    install_docker_linux
  elif [[ "$PLATFORM" == "macos" ]]; then
    install_docker_macos
  else
    PREREQ_OK=false
  fi
fi

if command -v docker &>/dev/null; then
  ok "Docker → $(command -v docker)"
  if ! docker info &>/dev/null 2>&1; then
    echo -e "${RED}[FAIL]${RESET}  Docker daemon is not running." >&2
    if [[ "$PLATFORM" == "linux" ]] && command -v systemctl &>/dev/null; then
      info "Attempting to start Docker daemon…"
      sudo systemctl start docker && ok "Docker daemon started." || PREREQ_OK=false
    else
      echo -e "  Start Docker and re-run." >&2
      PREREQ_OK=false
    fi
  fi
else
  PREREQ_OK=false
fi

# docker compose (v2 plugin preferred; fall back to standalone)
# DOCKER_COMPOSE is an array so it can be safely expanded as "${DOCKER_COMPOSE[@]}"
if docker compose version &>/dev/null 2>&1; then
  ok "docker compose (plugin v2)"
  DOCKER_COMPOSE=(docker compose)
elif command -v docker-compose &>/dev/null; then
  ok "docker-compose (standalone)"
  DOCKER_COMPOSE=(docker-compose)
else
  # Attempt to install the compose plugin on Linux
  if [[ "$PLATFORM" == "linux" ]]; then
    info "docker compose plugin not found — attempting to install…"
    if command -v apt-get &>/dev/null; then
      sudo apt-get install -y docker-compose-plugin 2>/dev/null || true
    elif command -v yum &>/dev/null; then
      sudo yum install -y docker-compose-plugin 2>/dev/null || true
    elif command -v dnf &>/dev/null; then
      sudo dnf install -y docker-compose-plugin 2>/dev/null || true
    fi
  fi
  if docker compose version &>/dev/null 2>&1; then
    ok "docker compose (plugin v2)"
    DOCKER_COMPOSE=(docker compose)
  else
    echo -e "${RED}[MISS]${RESET}  docker compose not found." \
      " Install the Compose plugin: https://docs.docker.com/compose/install/" >&2
    PREREQ_OK=false
    DOCKER_COMPOSE=(docker compose)   # placeholder so -u doesn't error later
  fi
fi

# openssl — required for secret generation
if ! command -v openssl &>/dev/null; then
  if [[ "$PLATFORM" == "linux" ]]; then
    install_openssl_linux
  elif [[ "$PLATFORM" == "macos" ]] && command -v brew &>/dev/null; then
    brew install openssl
  else
    echo -e "${RED}[MISS]${RESET}  OpenSSL not found." \
      " Install via your package manager (apt/brew install openssl)." >&2
    PREREQ_OK=false
  fi
fi
if command -v openssl &>/dev/null; then
  ok "OpenSSL → $(command -v openssl)"
else
  PREREQ_OK=false
fi

# curl — optional; used only for the post-install health check
if ! command -v curl &>/dev/null; then
  if [[ "$PLATFORM" == "linux" ]]; then
    install_curl_linux
  fi
fi
command -v curl &>/dev/null && ok "curl → $(command -v curl)" || \
  warn "curl not found; post-install health check will be skipped."

# git — optional; needed only for the GitHub-import feature
check_cmd git "git" "Install via your package manager." || true

[[ "$PREREQ_OK" == "true" ]] || die "Install missing prerequisites and re-run."

# ── Configure .env ────────────────────────────────────────────────────────────
echo ""
echo "────────────────────────────────────────────────────────────────"
info "Configuring environment…"

if [[ ! -f "$REPO_ROOT/.env" ]]; then
  cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
  info "Created .env from .env.example"
fi

# Generate cryptographically secure random secrets
DB_PASSWORD="$(openssl rand -hex 32)"
SITE_DB_PASSWORD="$(openssl rand -hex 32)"
ADMIN_SECRET_KEY="$(openssl rand -hex 64)"

# Interactive (or default) configuration prompts
echo ""
if [[ "$NON_INTERACTIVE" != "true" ]]; then
  echo -e "  Press ${BOLD}Enter${RESET} to accept defaults shown in brackets."
  echo ""
fi

prompt DOMAIN_SUFFIX "Internal domain suffix  (sites → <name>.<suffix>)" "link"
echo ""
echo -e "  ${BOLD}Panel bind address:${RESET}"
echo -e "  • ${CYAN}0.0.0.0:8000${RESET}   (default) — accessible from any host on your LAN"
echo -e "  • ${CYAN}127.0.0.1:8000${RESET}  — accessible only from this machine"
echo -e "  ${YELLOW}⚠  Use 0.0.0.0 only on trusted networks.${RESET}"
echo ""
prompt PANEL_PORT   "Control-plane bind address (host:port)" "0.0.0.0:8000"
prompt SFTP_PORT    "SFTP host port" "2222"

# ── LAN IP ────────────────────────────────────────────────────────────────────
# Auto-detect the primary LAN IP of this machine as the default.
detect_lan_ip() {
  if [[ "$PLATFORM" == "linux" ]]; then
    # Pick the IP of the default route interface, if available.
    local iface
    iface="$(ip route show default 2>/dev/null | awk '/default/ {print $5; exit}')"
    if [[ -n "$iface" ]]; then
      ip -4 addr show "$iface" 2>/dev/null \
        | awk '/inet / {gsub(/\/.*/, "", $2); print $2; exit}'
    else
      hostname -I 2>/dev/null | awk '{print $1}'
    fi
  elif [[ "$PLATFORM" == "macos" ]]; then
    ipconfig getifaddr en0 2>/dev/null \
      || ipconfig getifaddr en1 2>/dev/null \
      || true
  fi
}

DETECTED_IP="$(detect_lan_ip)"
echo ""
echo -e "  ${BOLD}LAN IP of this server:${RESET}"
echo -e "  This is used as the DNS A-record target for all *.${DOMAIN_SUFFIX} sites."
echo -e "  Clients must point their DNS resolver at this IP to resolve site names."
echo ""
prompt HOST_LAN_IP "Server LAN IP" "${DETECTED_IP:-192.168.1.1}"

# ── Port-53 DNS forwarder ─────────────────────────────────────────────────────
# CoreDNS defaults to host port 5353 to avoid conflicts with systemd-resolved.
# Standard DNS clients (browsers, routers) use port 53, so we ask whether to
# start the optional dns-forwarder sidecar that listens on port 53.
ENABLE_DNS53=false
echo ""
echo -e "  ${BOLD}DNS port-53 forwarding:${RESET}"
echo -e "  By default CoreDNS listens on host port ${CYAN}5353${RESET}."
echo -e "  Enable the ${CYAN}dns-forwarder${RESET} container to also listen on port ${CYAN}53${RESET},"
echo -e "  so that routers and devices can use this server as a standard DNS resolver."
echo -e "  ${YELLOW}⚠  Port 53 must be free on this host (disable systemd-resolved if needed).${RESET}"
echo ""
if [[ "$NON_INTERACTIVE" != "true" ]]; then
  read -r -p "  Enable port-53 DNS forwarding? [y/N]: " _dns53_choice
  [[ "${_dns53_choice,,}" == "y" ]] && ENABLE_DNS53=true
fi

if [[ "$ENABLE_DNS53" == "true" && "$PLATFORM" == "linux" ]]; then
  # Check if something is already listening on port 53.
  if ss -ulnp 2>/dev/null | grep -q ':53 ' || ss -tlnp 2>/dev/null | grep -q ':53 '; then
    echo ""
    warn "A service is already listening on port 53 (likely systemd-resolved)."
    echo -e "  To free the port, run:"
    echo -e "    ${CYAN}sudo systemctl disable --now systemd-resolved${RESET}"
    echo -e "    ${CYAN}sudo rm /etc/resolv.conf${RESET}"
    echo -e "    ${CYAN}echo 'nameserver 1.1.1.1' | sudo tee /etc/resolv.conf${RESET}"
    echo ""
    if [[ "$NON_INTERACTIVE" != "true" ]]; then
      read -r -p "  Disable systemd-resolved now and continue? [y/N]: " _dis_resolved
      if [[ "${_dis_resolved,,}" == "y" ]]; then
        sudo systemctl disable --now systemd-resolved 2>/dev/null && \
          sudo rm -f /etc/resolv.conf && \
          echo "nameserver 1.1.1.1" | sudo tee /etc/resolv.conf >/dev/null
        ok "systemd-resolved disabled; /etc/resolv.conf updated"
      else
        warn "Skipping port-53 forwarding — port 53 is still in use."
        ENABLE_DNS53=false
      fi
    else
      warn "Non-interactive mode: skipping systemd-resolved disable. Set DNS_PORT=53 manually."
      ENABLE_DNS53=false
    fi
  fi
fi

# Generate session cookie signing key
SESSION_SECRET_KEY="$(openssl rand -hex 64)"

# Write / update .env
set_env DB_PASSWORD        "$DB_PASSWORD"
set_env SITE_DB_PASSWORD   "$SITE_DB_PASSWORD"
set_env ADMIN_SECRET_KEY   "$ADMIN_SECRET_KEY"
set_env SESSION_SECRET_KEY "$SESSION_SECRET_KEY"
set_env DOMAIN_SUFFIX      "$DOMAIN_SUFFIX"
set_env PANEL_PORT         "$PANEL_PORT"
set_env SFTP_PORT          "$SFTP_PORT"
set_env HOST_LAN_IP        "$HOST_LAN_IP"

ok ".env written"

# ── Systemd service (Linux only, opt-in) ──────────────────────────────────────
if [[ "$INSTALL_SERVICE" == "true" ]]; then
  echo ""
  echo "────────────────────────────────────────────────────────────────"
  if [[ "$PLATFORM" != "linux" ]]; then
    warn "systemd service installation is Linux-only — skipping."
  elif ! command -v systemctl &>/dev/null; then
    warn "systemctl not found — skipping service installation."
  else
    SERVICE_FILE="/etc/systemd/system/linkhosting.service"
    info "Installing systemd service -> $SERVICE_FILE"
    DNS_PROFILE_FLAG=""
    [[ "$ENABLE_DNS53" == "true" ]] && DNS_PROFILE_FLAG="--profile dns-forwarder "
    sudo tee "$SERVICE_FILE" >/dev/null <<UNIT
[Unit]
Description=LinkHosting Docker Compose Stack
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${REPO_ROOT}
ExecStart=/usr/bin/docker compose ${DNS_PROFILE_FLAG}up -d --remove-orphans
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
UNIT
    sudo systemctl daemon-reload
    sudo systemctl enable linkhosting.service
    ok "linkhosting.service enabled (auto-starts on boot)"
  fi
fi

# ── Start the stack ───────────────────────────────────────────────────────────
echo ""
echo "────────────────────────────────────────────────────────────────"
info "Starting LinkHosting stack (first run may take a few minutes)..."
if [[ "$ENABLE_DNS53" == "true" ]]; then
  "${DOCKER_COMPOSE[@]}" --profile dns-forwarder up -d --build
else
  "${DOCKER_COMPOSE[@]}" up -d --build
fi

# ── Worker readiness check ────────────────────────────────────────────────────
echo ""
info "Verifying worker container readiness…"
WORKER_OK=false
WORKER_MAX_WAIT=30; WORKER_WAITED=0
until "${DOCKER_COMPOSE[@]}" ps worker 2>/dev/null | grep -q "running\|Up"; do
  sleep 3; WORKER_WAITED=$((WORKER_WAITED + 3))
  if [[ $WORKER_WAITED -ge $WORKER_MAX_WAIT ]]; then
    break
  fi
done

if "${DOCKER_COMPOSE[@]}" ps worker 2>/dev/null | grep -q "running\|Up"; then
  # Verify the worker can reach the Docker socket via the SDK
  if "${DOCKER_COMPOSE[@]}" exec -T worker \
      python -c "import docker; docker.DockerClient(base_url='unix:///var/run/docker.sock').ping()" \
      2>/dev/null; then
    ok "Worker is running and can reach the Docker socket ✔"
    WORKER_OK=true
  else
    warn "Worker is running but cannot reach the Docker socket."
    warn "Check that /var/run/docker.sock is mounted and the socket is accessible."
  fi
else
  warn "Worker container did not start within ${WORKER_MAX_WAIT}s."
  warn "Run '${DOCKER_COMPOSE[*]} logs worker' to see the error."
fi

# ── Health check ─────────────────────────────────────────────────────────────
BIND_ADDR="${PANEL_PORT:-127.0.0.1:8000}"
HEALTH_HOST="${BIND_ADDR%:*}"
HEALTH_PORT="${BIND_ADDR##*:}"
[[ "$HEALTH_HOST" == "0.0.0.0" ]] && HEALTH_HOST="127.0.0.1"
HEALTH_URL="http://${HEALTH_HOST}:${HEALTH_PORT}/health"

if command -v curl &>/dev/null; then
  info "Waiting for API at ${HEALTH_URL}…"
  MAX_WAIT=60; WAITED=0
  until curl -sf "$HEALTH_URL" &>/dev/null; do
    sleep 3; WAITED=$((WAITED + 3))
    if [[ $WAITED -ge $MAX_WAIT ]]; then
      warn "Health check timed out.  The stack may still be starting."
      break
    fi
  done
  curl -sf "$HEALTH_URL" &>/dev/null && ok "API health check passed ✔"
fi

# ── Post-install summary ──────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}  LinkHosting installed successfully!${RESET}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo -e "  API / Swagger UI  ->  ${CYAN}http://${HEALTH_HOST}:${HEALTH_PORT}/docs${RESET}"
echo -e "  Web Panel         ->  ${CYAN}http://${HEALTH_HOST}:${HEALTH_PORT}/panel/${RESET}"
echo -e "  Health endpoint   ->  ${CYAN}http://${HEALTH_HOST}:${HEALTH_PORT}/health${RESET}"
echo ""
echo -e "  ${BOLD}Admin Password:${RESET}   ${YELLOW}${ADMIN_SECRET_KEY}${RESET}"
echo -e "  ${YELLOW}⚠  Save the admin password above — it is stored in .env and not shown again.${RESET}"
echo ""
echo -e "  ${BOLD}Secrets saved to:${RESET} ${REPO_ROOT}/.env"
echo -e "  ${YELLOW}⚠  Keep .env private — it contains database passwords and API keys.${RESET}"
echo ""
echo -e "  ${BOLD}DNS configuration:${RESET}"
if [[ -n "$HOST_LAN_IP" ]]; then
  echo -e "  DNS A-records will point *.${DOMAIN_SUFFIX} → ${CYAN}${HOST_LAN_IP}${RESET}"
else
  echo -e "  ${YELLOW}⚠  HOST_LAN_IP is not set — DNS records will NOT be created for new sites.${RESET}"
  echo -e "     Set HOST_LAN_IP in ${REPO_ROOT}/.env and restart: docker compose up -d"
fi
if [[ "$ENABLE_DNS53" == "true" ]]; then
  echo -e "  Port-53 forwarder ${GREEN}enabled${RESET} — point your router's DNS to ${CYAN}${HOST_LAN_IP}${RESET}"
  echo -e "  Verify: ${CYAN}dig mysite.${DOMAIN_SUFFIX} @${HOST_LAN_IP}${RESET}"
else
  echo -e "  CoreDNS is listening on host port ${CYAN}5353${RESET} (not 53)."
  echo -e "  To use standard DNS clients, enable port-53 forwarding:"
  echo -e "    ${CYAN}docker compose --profile dns-forwarder up -d${RESET}"
  echo -e "  Or query on port 5353 directly:"
  echo -e "    ${CYAN}dig mysite.${DOMAIN_SUFFIX} @${HOST_LAN_IP:-<server-ip>} -p 5353${RESET}"
fi
echo ""
echo -e "  ${BOLD}Next steps:${RESET}"
echo -e "  1. Log in to the panel  -> ${CYAN}http://${HEALTH_HOST}:${HEALTH_PORT}/panel/${RESET}"
echo -e "  2. Create a site        -> ${CYAN}./scripts/create-site.sh mysite static${RESET}"
echo -e "  3. Deploy it            -> ${CYAN}./scripts/deploy-site.sh mysite${RESET}"
echo -e "  4. Issue TLS cert       -> ${CYAN}./scripts/create-cert.sh mysite${RESET}"
echo ""
echo "────────────────────────────────────────────────────────────────"