from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql://linkhosting:linkhosting@db:5432/linkhosting"

    # Docker
    docker_socket: str = "unix:///var/run/docker.sock"
    docker_network: str = "linkhosting"
    sites_base_dir: str = "/data/sites"
    certs_base_dir: str = "/data/certs"
    sftp_base_dir: str = "/data/sftp"

    # Internal CA
    ca_root_cert: str = "/data/certs/ca/root.crt"

    # Proxy
    proxy_config_dir: str = "/data/proxy/conf.d"

    # Auth
    admin_secret_key: str = "change-me-in-production"
    admin_token_expire_minutes: int = 60

    # Site domain suffix
    domain_suffix: str = "link"

    # Dev mode (skip real Docker/system calls)
    dev_mode: bool = False


settings = Settings()
