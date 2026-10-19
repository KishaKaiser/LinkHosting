"""Caps on the logs Docker keeps for the containers LinkHosting creates.

Without a limit Docker's default ``json-file`` driver keeps every log line for as long as the container exists, so a
chatty site can slowly fill the disk. The LinkHosting stack itself already uses the same cap in docker-compose.yml;
this applies it to the containers the panel creates for sites (static/node/python sites, WordPress and PL_CMS).

A container keeps at most ``LOG_MAX_FILES`` files of ``LOG_MAX_SIZE`` each, then the oldest lines are dropped.
"""

LOG_DRIVER = "json-file"
LOG_MAX_SIZE = "10m"
LOG_MAX_FILES = "3"


def compose_logging() -> dict:
    """The ``logging:`` block for a service in a generated docker-compose.yml."""
    return {"driver": LOG_DRIVER, "options": {"max-size": LOG_MAX_SIZE, "max-file": LOG_MAX_FILES}}


def docker_log_config() -> dict:
    """The ``log_config`` argument for the Docker SDK's ``containers.run``."""
    return {"Type": LOG_DRIVER, "Config": {"max-size": LOG_MAX_SIZE, "max-file": LOG_MAX_FILES}}
