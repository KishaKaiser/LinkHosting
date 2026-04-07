#!/usr/bin/env python3
"""
LinkHosting CLI — Python replacement for the shell helper scripts.

Reads configuration from environment variables or the nearest .env file:
  LINKHOSTING_API    API base URL  (default: http://127.0.0.1:8000)
  LINKHOSTING_TOKEN  Bearer token  (default: value of ADMIN_SECRET_KEY in .env)

Usage:
  lh.py create-site <name> <type> [--domain D] [--image I] [--upstream U] [--github URL] [--branch B]
  lh.py deploy      <name>
  lh.py stop        <name>
  lh.py delete      <name>
  lh.py status      <name>
  lh.py list
  lh.py cert        <name>
  lh.py create-db   <name> [postgres|mysql]
  lh.py create-sftp <name>
  lh.py jobs        <name>
  lh.py health

Site types: static | php | node | python | proxy | wordpress
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


# ── Config loading ─────────────────────────────────────────────────────────────

def _load_dotenv(start: Path) -> dict[str, str]:
    """Walk from *start* upward looking for a .env file; parse KEY=VALUE pairs."""
    for directory in [start, *start.parents]:
        env_file = directory / ".env"
        if env_file.is_file():
            result: dict[str, str] = {}
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                # Strip surrounding quotes if present
                val = val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                    val = val[1:-1]
                result[key.strip()] = val
            return result
    return {}


def _get_config() -> tuple[str, str]:
    """Return (api_url, token)."""
    env = _load_dotenv(Path.cwd())

    api_url = os.environ.get("LINKHOSTING_API") or env.get("LINKHOSTING_API", "http://127.0.0.1:8000")
    api_url = api_url.rstrip("/")

    token = os.environ.get("LINKHOSTING_TOKEN") or env.get("ADMIN_SECRET_KEY", "")
    if not token:
        _die("No API token found. Set LINKHOSTING_TOKEN or ensure ADMIN_SECRET_KEY is in .env")

    return api_url, token


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _request(method: str, url: str, token: str, body: dict | None = None) -> dict | list | None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            if raw:
                return json.loads(raw)
            return None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            detail = json.loads(raw).get("detail", raw.decode())
        except Exception:
            detail = raw.decode()
        _die(f"HTTP {exc.code} {exc.reason}: {detail}")
    except urllib.error.URLError as exc:
        _die(f"Connection error: {exc.reason}")


def _get(api_url: str, token: str, path: str) -> dict | list | None:
    return _request("GET", f"{api_url}{path}", token)


def _post(api_url: str, token: str, path: str, body: dict | None = None) -> dict | list | None:
    return _request("POST", f"{api_url}{path}", token, body)


def _delete(api_url: str, token: str, path: str) -> None:
    _request("DELETE", f"{api_url}{path}", token)


# ── Output ─────────────────────────────────────────────────────────────────────

def _print(data: dict | list | None) -> None:
    if data is not None:
        print(json.dumps(data, indent=2, default=str))


def _die(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(1)


def _ok(msg: str) -> None:
    print(f"[ OK ]  {msg}")


# ── Subcommands ────────────────────────────────────────────────────────────────

def cmd_health(api_url: str, token: str, _args: argparse.Namespace) -> None:
    # Health endpoint is unauthenticated
    req = urllib.request.Request(f"{api_url}/health", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            _print(json.loads(resp.read()))
    except urllib.error.URLError as exc:
        _die(f"Connection error: {exc.reason}")


def cmd_list(api_url: str, token: str, _args: argparse.Namespace) -> None:
    data = _get(api_url, token, "/sites")
    _print(data)


def cmd_status(api_url: str, token: str, args: argparse.Namespace) -> None:
    data = _get(api_url, token, f"/sites/{args.name}")
    _print(data)


def cmd_create_site(api_url: str, token: str, args: argparse.Namespace) -> None:
    body: dict = {"name": args.name, "site_type": args.type}
    if args.domain:
        body["domain"] = args.domain
    if args.image:
        body["image"] = args.image
    if args.upstream:
        body["upstream_url"] = args.upstream
    if args.github:
        body["github_repo"] = args.github
    if args.branch:
        body["github_branch"] = args.branch

    print(f"Creating site '{args.name}' (type={args.type})…")
    data = _post(api_url, token, "/sites", body)
    _print(data)
    _ok(f"Site '{args.name}' created.")
    print(f"\n  Deploy:    lh.py deploy {args.name}")
    print(f"  TLS cert:  lh.py cert {args.name}")
    print(f"  Database:  lh.py create-db {args.name}")
    print(f"  SFTP:      lh.py create-sftp {args.name}")


def cmd_deploy(api_url: str, token: str, args: argparse.Namespace) -> None:
    print(f"Deploying site '{args.name}'…")
    data = _post(api_url, token, f"/sites/{args.name}/deploy")
    _print(data)
    _ok(f"Site '{args.name}' deploy triggered.")
    print("  Add a DNS A record for the site's domain pointing to this host's IP.")


def cmd_stop(api_url: str, token: str, args: argparse.Namespace) -> None:
    print(f"Stopping site '{args.name}'…")
    data = _post(api_url, token, f"/sites/{args.name}/stop")
    _print(data)
    _ok(f"Site '{args.name}' stopped.")


def cmd_delete(api_url: str, token: str, args: argparse.Namespace) -> None:
    print(f"Deleting site '{args.name}'…")
    _delete(api_url, token, f"/sites/{args.name}")
    _ok(f"Site '{args.name}' deleted.")


def cmd_cert(api_url: str, token: str, args: argparse.Namespace) -> None:
    print(f"Issuing TLS certificate for '{args.name}'…")
    data = _post(api_url, token, f"/sites/{args.name}/cert")
    _print(data)
    _ok("Certificate issued. The proxy will serve HTTPS for this site.")
    print("\nTo trust the CA on client machines:")
    print(f"  curl {api_url}/ca.crt -o linkhosting-ca.crt")
    print("  See docs/ca-trust.md for full instructions.")


def cmd_create_db(api_url: str, token: str, args: argparse.Namespace) -> None:
    engine = args.engine or "postgres"
    print(f"Creating {engine} database for site '{args.name}'…")
    data = _post(api_url, token, f"/sites/{args.name}/database", {"engine": engine})
    _print(data)
    print("\n⚠  Store the password above — it will NOT be shown again.")


def cmd_create_sftp(api_url: str, token: str, args: argparse.Namespace) -> None:
    print(f"Creating SFTP account for site '{args.name}'…")
    data = _post(api_url, token, f"/sites/{args.name}/sftp")
    _print(data)

    if isinstance(data, dict):
        print("\n⚠  Store the password above — it will NOT be shown again.")
        host = data.get("ssh_host", "127.0.0.1")
        port = data.get("ssh_port", 2222)
        user = data.get("username", "?")
        print(f"\nSFTP connection:\n  sftp -P {port} {user}@{host}")


def cmd_jobs(api_url: str, token: str, args: argparse.Namespace) -> None:
    data = _get(api_url, token, f"/sites/{args.name}/jobs")
    _print(data)


# ── Argument parser ────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lh.py",
        description="LinkHosting CLI — manage sites, certs, databases, and SFTP accounts.",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # health
    sub.add_parser("health", help="Check API health")

    # list
    sub.add_parser("list", help="List all sites")

    # status
    p = sub.add_parser("status", help="Get site details")
    p.add_argument("name", help="Site name")

    # create-site
    p = sub.add_parser("create-site", help="Create a new site")
    p.add_argument("name", help="Site name")
    p.add_argument("type", help="Site type: static|php|node|python|proxy|wordpress")
    p.add_argument("--domain", default="", help="Custom domain (auto-generated if omitted)")
    p.add_argument("--image", default="", help="Custom Docker image")
    p.add_argument("--upstream", default="", help="Upstream URL (proxy type)")
    p.add_argument("--github", default="", help="GitHub repo URL to import")
    p.add_argument("--branch", default="", help="GitHub branch (default: main)")

    # deploy
    p = sub.add_parser("deploy", help="Deploy a site")
    p.add_argument("name", help="Site name")

    # stop
    p = sub.add_parser("stop", help="Stop a site")
    p.add_argument("name", help="Site name")

    # delete
    p = sub.add_parser("delete", help="Delete a site")
    p.add_argument("name", help="Site name")

    # cert
    p = sub.add_parser("cert", help="Issue a TLS certificate for a site")
    p.add_argument("name", help="Site name")

    # create-db
    p = sub.add_parser("create-db", help="Create a database for a site")
    p.add_argument("name", help="Site name")
    p.add_argument("engine", nargs="?", default="postgres", help="postgres|mysql (default: postgres)")

    # create-sftp
    p = sub.add_parser("create-sftp", help="Create an SFTP account for a site")
    p.add_argument("name", help="Site name")

    # jobs
    p = sub.add_parser("jobs", help="List deploy jobs for a site")
    p.add_argument("name", help="Site name")

    return parser


_COMMANDS = {
    "health":      cmd_health,
    "list":        cmd_list,
    "status":      cmd_status,
    "create-site": cmd_create_site,
    "deploy":      cmd_deploy,
    "stop":        cmd_stop,
    "delete":      cmd_delete,
    "cert":        cmd_cert,
    "create-db":   cmd_create_db,
    "create-sftp": cmd_create_sftp,
    "jobs":        cmd_jobs,
}


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    api_url, token = _get_config()

    fn = _COMMANDS[args.command]
    fn(api_url, token, args)


if __name__ == "__main__":
    main()
