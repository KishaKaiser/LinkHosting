from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql://linkhosting:linkhosting@db:5432/linkhosting"

    # Docker
    docker_socket: str = "unix:///var/run/docker.sock"
    docker_network: str = "linkhosting"
    sites_base_dir: str = "/srv/linkhosting/sites"
    certs_base_dir: str = "/data/certs"
    sftp_base_dir: str = "/data/sftp"

    # Internal CA
    ca_root_cert: str = "/data/certs/ca/root.crt"

    # Proxy
    proxy_config_dir: str = "/data/proxy/conf.d"

    # Auth
    admin_secret_key: str = "change-me-in-production"
    admin_token_expire_minutes: int = 60
    session_secret_key: str = "change-me-session-secret"

    # Site domain suffix
    domain_suffix: str = "link"

    # Redis / RQ
    redis_url: str = "redis://redis:6379/0"

    # Dev mode (skip real Docker/system calls)
    dev_mode: bool = False

    # DNS
    dns_enabled: bool = True
    host_lan_ip: str = ""
    dns_hosts_file: str = "/data/dns/hosts"
    dns_container_name: str = "lh-dns"

    # Persistent admin key override (written by the password-change UI)
    admin_key_override_file: str = "/data/admin_secret_key"

    # GitHub Personal Access Token for cloning private repositories
    # Can also be set via GITHUB_TOKEN environment variable.
    github_token: str = ""
    # Path where the token is persisted across container restarts (written by the settings UI)
    github_token_override_file: str = "/data/github_token"


settings = Settings()
