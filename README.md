# crawl4ai-mcp

Remote **Streamable HTTP** MCP server that converts web pages to Markdown (and summaries) with [crawl4ai](https://github.com/unclecode/crawl4ai), using an **external CDP browser** only. Site-specific extractors ship as YAML under `configs/` and can be overridden via `CONFIG_DIR`.

This repository is independent of the `skills` / `md-this-page` skill copy.

## Requirements

- Python 3.11+ **or** Docker Compose
- An external CDP browser (`CDP_URL`). Recommended stack: **[CloakBrowser](https://github.com/CloakHQ/cloakbrowser) `cloakserve`** (see Docker below). Local Chrome remote debugging also works.

No bundled Chromium / headless fallback inside the MCP process.

## Docker Compose (CloakBrowser + MCP)

Uses the official CloakBrowser image in CDP server mode (`cloakserve`) and this repo’s MCP image. Aligns with [CloakBrowser Docker Compose](https://github.com/CloakHQ/cloakbrowser): license via `CLOAKBROWSER_LICENSE_KEY`, CDP on `127.0.0.1:9222`, healthcheck on `/json/version`.

```bash
cp .env.example .env
# set CLOAKBROWSER_LICENSE_KEY (required; free key: https://cloakbrowser.dev/free)

docker compose up -d --build
docker compose logs -f mcp
```

- MCP: `http://127.0.0.1:8000/mcp` (Bearer key in logs / volume)
- CDP (host only): `http://127.0.0.1:9222` — do not publish to the public internet
- Inside Compose, MCP uses `CDP_URL=http://cloakbrowser:9222`

Show connection info from a one-off container (same data volume):

```bash
docker compose run --rm -e CRAWL4AI_MCP_DATA_DIR=/data mcp crawl4ai-mcp info
```

Stop:

```bash
docker compose down
```

## Install (local Python)

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e '.[dev]'
```

## Run the MCP server (local)

Point `CDP_URL` at CloakBrowser or Chrome:

```bash
# e.g. after: docker compose up -d cloakbrowser
export CDP_URL=http://127.0.0.1:9222
crawl4ai-mcp serve
```

On start the process:

1. Validates `CDP_URL`
2. Uses `API_KEY` if set, otherwise generates one and stores it under `~/.crawl4ai-mcp/`
3. Writes `~/.crawl4ai-mcp/connection.json`
4. Logs the MCP URL and API key

Defaults: `MCP_HOST=127.0.0.1`, `MCP_PORT=8000`, endpoint path `/mcp`.

Show connection details later:

```bash
crawl4ai-mcp info
```

Clients should call Streamable HTTP at the logged URL with header:

```http
Authorization: Bearer <api_key>
```

## MCP tools (v1)

| Tool | Purpose |
| --- | --- |
| `convert_url` | URL → Markdown |
| `extract_summary` | URL → plain-text summary |
| `list_site_strategies` | List builtin/user site configs |

## Site strategies

Builtin YAML lives in `configs/` (WeChat, Zhihu, CSDN, …). Point `CONFIG_DIR` at a directory of extra `*.yaml` files to override by `name` or prefer user domain matches.

Example fields: `name`, `domains`, `css_selector`, `css_selector_fallbacks`, `excluded_selector`, `wait_for`, `js_snippets` (`snippet:lazy_images`), metadata selectors.

## Environment

| Variable | Meaning |
| --- | --- |
| `CDP_URL` | Required CDP HTTP endpoint |
| `API_KEY` | Optional fixed Bearer token |
| `CONFIG_DIR` | Optional user strategy directory |
| `MCP_HOST` / `MCP_PORT` | Bind address |
| `CRAWL4AI_MCP_DATA_DIR` | Override `~/.crawl4ai-mcp` |

## Tests

```bash
.venv/bin/python -m pytest -q
```

Live CDP / public URL checks are optional and not required for CI.

## Non-goals (v1)

- Web search or generic query tools beyond convert/summary/list
- Changes to the `skills` repository

## Design

- Spec: `docs/superpowers/specs/2026-11-08-crawl4ai-mcp-design.md`
- Plan: `docs/superpowers/plans/2026-11-08-crawl4ai-mcp.md`
