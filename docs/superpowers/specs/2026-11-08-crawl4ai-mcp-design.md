# crawl4ai-mcp Design

Date: 2026-11-08  
Status: Approved for implementation planning

## Goal

Build a standalone remote MCP service at `/home/jp3-wchajl/crawl4ai-mcp` that converts web pages to Markdown (and summaries) using crawl4ai over an **external CDP browser**. Site-specific crawl/convert behavior is driven by YAML configs (builtin presets migrated from the existing `md-this-page` skill, plus user overrides). The `skills` repository is left unchanged in v1 (independent copy/evolution).

## Decisions locked

| Topic | Choice |
| --- | --- |
| Location | `/home/jp3-wchajl/crawl4ai-mcp` |
| Relation to `skills` | Keep existing skill as-is; do not delete or rewrite it in v1 |
| v1 scope | URL → Markdown / summary + site strategies; no web search / generic query tools |
| Browser | External CDP only (`CDP_URL` env); no embedded/headless fallback |
| MCP transport | Streamable HTTP (remote) |
| Auth | Bearer API key; auto-generate if unset; persist; log + connection JSON + CLI |
| Docker | Out of v1 delivery; document env/mount conventions only |

## Architecture

Thin MCP server over a small library extracted from `skills/md-this-page` (`crawler`, `converter`), with strategies loaded from YAML instead of a hard-coded Python list.

```
crawl4ai-mcp/
  pyproject.toml
  README.md
  configs/                     # builtin site strategies (YAML)
    _snippets.yaml             # optional shared JS snippet library
    weixin.yaml
    zhihu.yaml
    ...
  src/crawl4ai_mcp/
    __init__.py
    server.py                  # Streamable HTTP MCP + Bearer auth
    cli.py                     # info / show-connection
    tools.py                   # MCP tool handlers
    crawler.py                 # CDP-required crawl
    converter.py               # Markdown + summary
    strategies.py              # load/merge configs
    models.py                  # strategy + IO models
    credentials.py             # API key generate/persist/load
  tests/
  docs/superpowers/specs/      # this design
```

**Runtime dependencies**

- `CDP_URL` (required): must be a compliant CDP endpoint (`GET /json/version` yields `webSocketDebuggerUrl`). Missing or invalid → **process exits at startup**.
- API key: if `API_KEY` is set, use it; otherwise generate a random key and persist under a data directory (default `~/.crawl4ai-mcp/`).
- Optional `CONFIG_DIR`: user strategy YAML directory (overrides/extends builtins).
- Optional bind host/port for the HTTP server (sensible defaults, e.g. `127.0.0.1:8000`, documented in README).

**Startup side effects**

1. Validate `CDP_URL`.
2. Resolve API key (env or generate + persist).
3. Load strategies (builtin + `CONFIG_DIR`).
4. Write/update **connection JSON** (endpoint URL, transport type, Authorization header value or template).
5. Log MCP base URL/path and API key.
6. Serve Streamable HTTP MCP.

**CLI** (same package entrypoint, e.g. `crawl4ai-mcp info`): read persisted credentials/connection JSON and print address, key, and file paths. If no state exists yet, instruct the user to start the server once (or set `API_KEY` and start).

## MCP tools (v1)

| Tool | Purpose | Inputs | Outputs |
| --- | --- | --- | --- |
| `convert_url` | URL → Markdown | `url`; optional `include_metadata`, `include_images`, `include_links`, `timeout_sec` | Markdown text + matched strategy name |
| `extract_summary` | URL → summary | `url`; optional `max_length`, `timeout_sec` | Summary text + strategy name |
| `list_site_strategies` | List loaded strategies | optional filter | name, domains, source (`builtin` / `user`) |

**Data flow (convert / extract)**

1. Authenticate Bearer token.
2. Validate `http://` or `https://` URL.
3. Match strategy by domain (user overrides win).
4. Crawl via crawl4ai using external CDP and strategy fields (`wait_for`, `js_snippets`, selectors, etc.).
5. Convert to Markdown or summary.
6. On failure, return an explicit tool error (CDP down, timeout, empty body, etc.); never present truncated/failed crawls as success.

Results are returned through MCP only; the server does not persist page output to disk in v1.

## Site configuration

**Format:** one YAML file per site under `configs/` (builtins) and optional `CONFIG_DIR`.

**Schema** (aligned with existing `SiteStrategy`):

```yaml
name: 微信公众号
domains:
  - mp.weixin.qq.com
  - weixin.qq.com
css_selector: "#js_content"       # optional; single selector
css_selector_fallbacks: []        # optional
excluded_selector: "..."          # optional; comma-separated
wait_for: "css:#js_content"       # optional
js_snippets: []                   # optional strings and/or named builtin snippet refs
title_suffixes:
  - " - 微信公众平台"
title_selector: null
author_selector: null
date_selector: null
```

**Load rules**

1. Load all builtin `configs/*.yaml` (excluding snippet library files prefixed with `_` as strategies).
2. If `CONFIG_DIR` is set, load `*.yaml` from it.
3. Same `name` or overlapping primary domain: user config overrides builtin.
4. Domain match remains exact host or subdomain (reject lookalike hosts).
5. No match → generic crawl4ai extraction (no site-specific selector).
6. Invalid YAML / missing `name` or `domains`: skip file, log warning; process continues (v1 default). Optional strict mode may be added later; not required for v1.

**Builtin content:** migrate strategies from `skills/md-this-page/src/strategies.py` (WeChat, Zhihu, CSDN, Juejin, etc.) into YAML. Shared JS (lazy images, Zhihu math) lives as named snippets.

## Auth and connection JSON

- Header: `Authorization: Bearer <api_key>`.
- Missing/wrong key → HTTP 401 before tool dispatch.
- Auto-generated keys are persisted so restarts remain stable unless the user deletes state or sets `API_KEY`.
- Connection JSON fields (minimum): transport (`streamable-http`), URL, API key (or auth header), created/updated timestamp. Exact filename under the data directory is an implementation detail; CLI must discover it.

## Error handling

| Case | Behavior |
| --- | --- |
| Missing/invalid API key on request | HTTP 401 |
| Missing/invalid `CDP_URL` at startup | Exit non-zero; do not serve |
| CDP disconnect mid-request | Tool error with remediation hint |
| Bad URL / timeout / empty content | Tool error; no fake success |
| One bad user config file | Skip + log; other strategies remain |

## Testing

- Unit: strategy load/override/domain match.
- Unit: converter fixtures → Markdown/summary.
- Unit: auth middleware (missing/wrong/valid key).
- Unit: credentials persistence + CLI info.
- Optional integration: live CDP + public URL (not required in default CI).

## Non-goals (v1)

- Docker / Compose images (document env only).
- Web search or generic “query page” tools beyond convert/summary/list.
- Bundled Chromium / headless fallback.
- Changes to the `skills` repository.
- OAuth / multi-tenant auth.

## Success criteria

- Server starts only with a working `CDP_URL`.
- Agent can call remote Streamable HTTP MCP with Bearer key and convert a public article to Markdown.
- WeChat (and other migrated) strategies behave equivalently to the skill for matched domains.
- User can drop a YAML into `CONFIG_DIR` and see it via `list_site_strategies` without code changes.
- `crawl4ai-mcp info` prints endpoint and API key from persisted connection state after first start.

## Later (out of this plan’s execution, but not forbidden to mention in README)

- Docker deployment.
- Search / richer crawl4ai-aligned query tools.
- Closer integration or replacement of the `skills` `md-this-page` / Rakazo variant.
