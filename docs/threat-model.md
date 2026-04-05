# LinkHosting — Threat Model

## Scope

This threat model covers the **LinkHosting internal hosting control plane** deployed on an Ubuntu 24.04 host within a **trusted internal network**. External internet access is explicitly out of scope.

---

## Assets

| Asset | Sensitivity | Notes |
|-------|-------------|-------|
| Internal CA private key (`ca.key`) | Critical | Compromise allows forging any site cert |
| Per-site TLS private keys | High | Allows MITM for that site |
| Control-plane API | High | Controls all provisioning |
| Site database credentials | High | Access to all site data |
| SFTP credentials | Medium | Site file access |
| Admin secret key | High | Signs admin JWTs |
| Site files | Medium | Depends on site content |

---

## Trust Boundaries

```
[Admin workstation]  ──LAN──►  [Control Plane API :8000]
[End users]          ──LAN──►  [Nginx Proxy :80/:443]
[SFTP clients]       ──LAN──►  [SFTP Server :2222]
                                        │
                              [Docker containers]
                                        │
                              [Site databases (internal)]
```

---

## Threats and Mitigations

### T1: Unauthorized API Access
- **Threat**: Attacker on the internal network calls control-plane API to create/delete sites
- **Impact**: Full control plane compromise
- **Mitigation**:
  - Bind API to `127.0.0.1:8000` by default (change `CONTROL_PLANE_PORT`)
  - Use `ADMIN_SECRET_KEY` for token-based auth (add auth middleware for production)
  - Firewall the control-plane port from LAN clients

### T2: CA Private Key Compromise
- **Threat**: Attacker reads `/data/certs/ca/ca.key`
- **Impact**: Can forge TLS certs for any internal domain
- **Mitigation**:
  - Restrict file permissions: `chmod 600 /data/certs/ca/ca.key`
  - Mount CA volume with `read-only` except during cert issuance
  - Consider hardware-backed CA (HSM/Yubikey) for high-security deployments
  - Rotate CA and revoke trust if key is suspected compromised

### T3: Container Escape
- **Threat**: Malicious site code escapes its Docker container
- **Impact**: Access to host or other containers
- **Mitigation**:
  - Do not run containers as root (use `--user` flag or `USER` in Dockerfile)
  - Use Docker's default `seccomp` and `AppArmor` profiles
  - Do not mount the Docker socket into site containers (only control-plane)
  - Consider `gVisor` (runsc) for untrusted workloads

### T4: SFTP Account Abuse
- **Threat**: Site owner uploads malicious files (e.g., PHP webshells)
- **Impact**: Code execution on site container
- **Mitigation**:
  - PHP: disable dangerous functions (`exec`, `system`, `passthru`) in `php.ini`
  - Scan uploads with ClamAV
  - SFTP chroot prevents accessing other sites' files

### T5: Database Credential Leakage
- **Threat**: Database password exposed in logs, API responses, or config files
- **Impact**: Unauthorized database access
- **Mitigation**:
  - Passwords returned only once at creation time (hashed in DB)
  - TLS on database connections (configure PostgreSQL SSL)
  - Database service on `backend` (internal-only) Docker network

### T6: Privilege Escalation via Docker Socket
- **Threat**: Control-plane container uses Docker socket to escape to host
- **Impact**: Full host compromise
- **Mitigation**:
  - Mount socket as read-only where possible
  - Consider Docker-in-Docker or Podman rootless for stronger isolation
  - Audit all container management calls

### T7: Insecure TLS Configuration
- **Threat**: Weak ciphers or protocols allow downgrade/MITM attacks
- **Impact**: Encrypted traffic decryption
- **Mitigation**:
  - Nginx configured with `TLSv1.2 TLSv1.3` only
  - Strong cipher suite (`HIGH:!aNULL:!MD5`)
  - HSTS headers (add to Nginx vhost templates for production)

---

## Out of Scope

- **External internet threats** — this system is intentionally internal-only
- **Physical access to server** — assumed trusted datacenter/closet
- **DNS poisoning** — use trusted internal DNS resolver

---

## Security Recommendations for Production

1. **Rotate the `ADMIN_SECRET_KEY`** to a cryptographically random 64-char string
2. **Change all default passwords** in `.env`
3. **Restrict `CONTROL_PLANE_PORT`** to admin host only (not LAN-wide)
4. **Enable firewall** (ufw) — only expose ports 80, 443, 2222 to LAN
5. **Back up CA key** securely (offline backup)
6. **Enable PostgreSQL TLS** for database connections
7. **Set up log aggregation** (forward `/var/log/nginx/` and container logs)
8. **Run containers as non-root** users
