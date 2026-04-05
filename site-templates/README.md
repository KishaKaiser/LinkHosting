# Site Templates

This directory contains Docker Compose fragment files for each supported site type.
The control-plane generates a per-site compose file from these templates when deploying a site.

## Site types

| File | Type | Description |
|------|------|-------------|
| `static.yml` | Static | Nginx serving static HTML/CSS/JS files |
| `php.yml` | PHP | PHP-FPM + Nginx |
| `node.yml` | Node.js | Node.js app (any framework) |
| `python.yml` | Python | Python WSGI/ASGI app (gunicorn/uvicorn) |
| `proxy.yml` | Reverse Proxy | Nginx reverse-proxying to an upstream URL |

## Usage

The control-plane uses these as Jinja2 templates. Variables are substituted at provisioning time.
You can also use them manually:

```bash
# Example: deploy a static site manually
docker compose -f site-templates/static.yml up -d
```
