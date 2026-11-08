# crawl4ai-mcp v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a remote Streamable HTTP MCP service that converts URLs to Markdown/summaries via external CDP, with YAML site strategies, auto API key, and a CLI to show connection info.

**Architecture:** Library core (strategies → CDP crawl → convert) behind MCP tools; Starlette/ASGI wraps the official MCP Python SDK Streamable HTTP app with Bearer auth; credentials and connection JSON persist under `~/.crawl4ai-mcp/`.

**Tech Stack:** Python 3.11+, `mcp` (MCPServer / streamable-http), `crawl4ai`, `beautifulsoup4`, `lxml`, `PyYAML`, `uvicorn`/`starlette` (via mcp), `pytest`.

**Spec:** `docs/superpowers/specs/2026-11-08-crawl4ai-mcp-design.md`

## Global Constraints

- Do not modify `/home/jp3-wchajl/skills` (copy/adapt code into this repo only).
- `CDP_URL` is required from the environment; no default localhost probe for serving; no headless fallback.
- Remote transport is Streamable HTTP only (`/mcp`); default bind `127.0.0.1:8000`.
- Auth is `Authorization: Bearer <api_key>`; auto-generate and persist if `API_KEY` unset.
- Data directory default: `~/.crawl4ai-mcp/` (`credentials` + `connection.json`).
- Package import root: `crawl4ai_mcp`; CLI entry: `crawl4ai-mcp`.
- v1 tools only: `convert_url`, `extract_summary`, `list_site_strategies`.
- Builtin strategies live as YAML under `configs/`; user overrides via `CONFIG_DIR`.

## Review Focus

- Request with valid key but malformed `Authorization` scheme (not `Bearer`) → 401.
- Strategy YAML that sets overlapping domains with a different `name` → user file wins by domain match order documented in loader tests.
- `convert_url` on non-http(s) URL → tool error string, not HTTP 500.
- Mid-request CDP failure after successful startup probe → tool error mentioning CDP, server stays up.
- `CONFIG_DIR` pointing at a missing directory → startup warning / empty user layer, builtins still load (do not crash).

---

## File map

| Path | Responsibility |
| --- | --- |
| `pyproject.toml` | package metadata, deps, scripts |
| `configs/_snippets.yaml` | named JS snippets |
| `configs/*.yaml` | builtin site strategies |
| `src/crawl4ai_mcp/models.py` | `SiteStrategy`, `CrawlResult`, connection record types |
| `src/crawl4ai_mcp/strategies.py` | load/merge/match |
| `src/crawl4ai_mcp/converter.py` | Markdown + summary |
| `src/crawl4ai_mcp/crawler.py` | CDP validation + crawl |
| `src/crawl4ai_mcp/credentials.py` | API key + connection JSON |
| `src/crawl4ai_mcp/tools.py` | pure tool handlers used by MCP |
| `src/crawl4ai_mcp/server.py` | MCP app + auth middleware + run |
| `src/crawl4ai_mcp/cli.py` | `info` / show connection |
| `src/crawl4ai_mcp/__main__.py` | `python -m crawl4ai_mcp` |
| `tests/` | unit tests per task |

---

### Task 1: Package scaffold + strategy model + YAML loader

**Files:**
- Create: `pyproject.toml`, `src/crawl4ai_mcp/__init__.py`, `src/crawl4ai_mcp/models.py`, `src/crawl4ai_mcp/strategies.py`, `tests/test_strategies.py`, `configs/_snippets.yaml` (minimal fixture for tests may live under `tests/fixtures/configs/`)

**Interfaces:**
- Produces:
  - `@dataclass SiteStrategy` with fields: `name: str`, `domains: tuple[str, ...]`, `css_selector: str | None`, `css_selector_fallbacks: tuple[str, ...]`, `excluded_selector: str | None`, `wait_for: str | None`, `js_snippets: list[str]`, `title_suffixes: tuple[str, ...]`, `title_selector` / `author_selector` / `date_selector: str | None`, `source: str` (`"builtin"` | `"user"`)
  - `SiteStrategy.matches(self, url: str) -> bool` (exact host or subdomain)
  - `load_strategies(builtin_dir: Path, user_dir: Path | None, snippets: dict[str, str] | None = None) -> list[SiteStrategy]`
  - `detect_strategy(strategies: list[SiteStrategy], url: str) -> SiteStrategy` (try `source=="user"` matches first, then others; fallback name `"普通网页"`, empty domains, `source="builtin"`)
  - Snippet refs in YAML: string starting with `snippet:` looks up `_snippets.yaml` keys; unknown key raises `ValueError` at load of that file (file skipped with warning if using tolerant load — **v1:** invalid file skipped + logged)

- [ ] **Step 1: Write failing tests** in `tests/test_strategies.py`

```python
def test_matches_subdomain_not_lookalike():
    s = SiteStrategy(name="知乎", domains=("zhihu.com",), source="builtin")
    assert s.matches("https://zhuanlan.zhihu.com/p/1")
    assert not s.matches("https://notzhihu.com/p/1")

def test_user_overrides_builtin_same_name(tmp_path):
    # write builtin + user YAML with same name, different css_selector
    # load_strategies → detect → assert user selector wins

def test_invalid_yaml_skipped(tmp_path, caplog):
    # broken YAML in user dir → other strategies still returned

def test_missing_user_dir_loads_builtins_only(tmp_path):
    # user_dir path that does not exist → builtins returned, no crash

def test_user_domain_overlap_different_name_prefers_user_order(tmp_path):
    # user strategy for same domain, different name, listed after load dedupe-by-name;
    # detect_strategy must return the user strategy when domains collide
    # (implement by appending user strategies and sorting so source=="user" is tried first)
```

- [ ] **Step 2: Run tests — expect FAIL** (`SiteStrategy` / `load_strategies` missing)

Run: `pytest tests/test_strategies.py -v`

- [ ] **Step 3: Implement models + loader**

Implement signatures above. Domain match: `host == d or host.endswith("." + d)`. Override rule: after loading builtins then user files, for each strategy keep last-wins by `name.casefold()`; also when matching URL, iterate list so user strategies are ordered before builtins **or** dedupe so only winners remain — pick **dedupe by name last-wins, user loaded after builtin**.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/crawl4ai_mcp/models.py src/crawl4ai_mcp/strategies.py src/crawl4ai_mcp/__init__.py tests/test_strategies.py configs/_snippets.yaml
git commit -m "feat: add strategy models and YAML loader"
```

---

### Task 2: Migrate builtin site YAML from md-this-page

**Files:**
- Create: `configs/weixin.yaml`, `zhihu.yaml`, `csdn.yaml`, `juejin.yaml`, `jianshu.yaml`, `bilibili.yaml`, `cnblogs.yaml`, `oschina.yaml`, `segmentfault.yaml`, complete `configs/_snippets.yaml` (`lazy_images`, `zhihu_math`)
- Modify: none in skills repo
- Test: `tests/test_builtin_configs.py`

**Interfaces:**
- Consumes: `load_strategies`
- Produces: builtin dir `configs/` loadable; `detect_strategy(..., "https://mp.weixin.qq.com/s/x").name == "微信公众号"`

- [ ] **Step 1: Write failing test** that loads repo `configs/` and asserts WeChat/Zhihu domain detection + snippet resolution non-empty for WeChat `js_snippets`

- [ ] **Step 2: Run — expect FAIL** (configs missing)

- [ ] **Step 3: Port strategies** from `/home/jp3-wchajl/skills/md-this-page/src/strategies.py` into YAML; put JS bodies in `_snippets.yaml`; reference as `snippet:lazy_images` / `snippet:zhihu_math`

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add configs/ tests/test_builtin_configs.py
git commit -m "feat: add builtin site strategy YAML configs"
```

---

### Task 3: Converter (Markdown + summary)

**Files:**
- Create: `src/crawl4ai_mcp/converter.py`, `tests/test_converter.py`, `tests/fixtures/sample_crawl.html` (small HTML)
- Adapt logic from `skills/md-this-page/src/converter.py` + `CrawlResult` fields needed

**Interfaces:**
- Consumes: `CrawlResult(url, title, author, date, markdown, html, success, error, strategy_name)` defined in `models.py` (add in this task if not present)
- Produces:
  - `convert_to_markdown(result: CrawlResult, *, include_metadata: bool = True, include_images: bool = True, include_links: bool = True, max_chars: int | None = None) -> str`
  - `extract_summary(result: CrawlResult, *, max_length: int = 3000) -> str`

- [ ] **Step 1: Write failing tests** with a minimal `CrawlResult` fixture: metadata on/off, strip images/links, summary length cap

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement converter** (port behavior; keep YAML front matter safety helpers)

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/crawl4ai_mcp/converter.py src/crawl4ai_mcp/models.py tests/test_converter.py tests/fixtures/
git commit -m "feat: add markdown and summary converter"
```

---

### Task 4: CDP gate + crawler (no headless fallback)

**Files:**
- Create: `src/crawl4ai_mcp/crawler.py`, `tests/test_crawler.py`
- Adapt from `skills/md-this-page/src/crawler.py` but **delete** local browser fallback paths

**Interfaces:**
- Produces:
  - `require_cdp_url(env: Mapping[str, str] | None = None) -> str` — reads `CDP_URL`; empty → raise `CdpConfigError`
  - `is_valid_cdp(cdp_url: str, timeout: float = 1.5) -> bool` — `/json/version` + `webSocketDebuggerUrl`
  - `assert_cdp_ready(cdp_url: str | None = None) -> str` — validate or raise `CdpConfigError`
  - `async def crawl_page(url: str, strategies: list[SiteStrategy], *, timeout_ms: int = 45000, verbose: bool = False, cdp_url: str | None = None) -> CrawlResult` — uses only CDP `BrowserConfig`; on browser connect failure return `CrawlResult(success=False, error=...)` (do not spawn local chrome)

- [ ] **Step 1: Write failing tests**
  - `test_require_cdp_url_missing` → raises
  - `test_is_valid_cdp_rejects_bad` (mock urlopen)
  - `test_crawl_page_does_not_fallback` (mock AsyncWebCrawler to raise connection error; assert error mentions CDP / connection and no second browser mode) — keep assertion on public behavior: `success is False` and `"cdp" in error.lower() or "connect" in error.lower()`

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement crawler** CDP-only; reuse selector fallback / MIN_ACCEPT_CHARS behavior from skill where practical

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/crawl4ai_mcp/crawler.py tests/test_crawler.py
git commit -m "feat: add CDP-only page crawler"
```

---

### Task 5: Credentials, connection JSON, CLI

**Files:**
- Create: `src/crawl4ai_mcp/credentials.py`, `src/crawl4ai_mcp/cli.py`, `src/crawl4ai_mcp/__main__.py`, `tests/test_credentials.py`, `tests/test_cli.py`
- Modify: `pyproject.toml` entry point `crawl4ai-mcp = crawl4ai_mcp.cli:main`

**Interfaces:**
- Produces:
  - `DEFAULT_DATA_DIR = Path.home() / ".crawl4ai-mcp"`
  - `resolve_api_key(env, data_dir) -> str` — use `API_KEY` if set (persist too); else load existing; else generate `secrets.token_urlsafe(32)`, persist
  - `write_connection_json(data_dir, *, host: str, port: int, path: str, api_key: str) -> Path` — write `connection.json` with keys: `transport`=`"streamable-http"`, `url`=`http://{host}:{port}{path}`, `api_key`, `authorization`=`Bearer ...`, `updated_at` ISO-8601
  - `load_connection(data_dir) -> dict | None`
  - CLI: `crawl4ai-mcp info` prints url, api_key, connection file path; exit 1 if missing with message to start server once

- [ ] **Step 1: Write failing tests** for generate/persist/stable reload; CLI info happy path + missing state

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement credentials + CLI** (`argparse`; subcommand `info`)

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/crawl4ai_mcp/credentials.py src/crawl4ai_mcp/cli.py src/crawl4ai_mcp/__main__.py pyproject.toml tests/test_credentials.py tests/test_cli.py
git commit -m "feat: add API key persistence and connection CLI"
```

---

### Task 6: Tool handlers + MCP server + Bearer auth

**Files:**
- Create: `src/crawl4ai_mcp/tools.py`, `src/crawl4ai_mcp/server.py`, `tests/test_tools.py`, `tests/test_auth_middleware.py`
- Modify: `pyproject.toml` deps (`mcp`), CLI add `serve` subcommand **or** `crawl4ai-mcp` default serve — prefer: `crawl4ai-mcp serve` and `crawl4ai-mcp info`

**Interfaces:**
- Produces:
  - `async def tool_convert_url(...) -> str` / `tool_extract_summary(...) -> str` / `tool_list_site_strategies(...) -> str` (JSON or readable text; include strategy name in convert/summary output header or trailing line `strategy: ...`)
  - `build_asgi_app(...)` → Starlette app = Bearer middleware wrapping `MCPServer(...).streamable_http_app(stateless_http=True, json_response=True)`
  - Middleware: if `Authorization` != `Bearer <exact key>` → `401`
  - `serve()`: `assert_cdp_ready()`; `resolve_api_key`; `load_strategies`; `write_connection_json`; log URL + api_key; `uvicorn.run` app on `HOST`/`PORT` (env `MCP_HOST` default `127.0.0.1`, `MCP_PORT` default `8000`, path `/mcp`)
  - Register tools: `convert_url`, `extract_summary`, `list_site_strategies`

- [ ] **Step 1: Write failing tests**
  - tools: invalid URL (`ftp://...`) returns error text without calling crawl (mock crawl)
  - auth: ASGI test client without key → 401; with `Bearer <key>` → not 401; with `Basic ...` or raw key and no `Bearer` → 401
  - optional: mock crawl raising connection error → tool result text mentions CDP/connect

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement tools + server**

Use current `mcp` SDK: `MCPServer` + `streamable_http_app` (or `run(transport="streamable-http", ...)` if middleware can wrap equivalently — **prefer explicit ASGI wrap** so Bearer runs first). Pin dependency to a version that provides Streamable HTTP; if installed SDK still uses `FastMCP`, use that name but keep transport/`/mcp` behavior identical.

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/crawl4ai_mcp/tools.py src/crawl4ai_mcp/server.py src/crawl4ai_mcp/cli.py pyproject.toml tests/test_tools.py tests/test_auth_middleware.py
git commit -m "feat: add Streamable HTTP MCP server with Bearer auth"
```

---

### Task 7: README + verification sweep

**Files:**
- Create: `README.md`
- Modify: none required beyond fixing any gaps found by the sweep

**Interfaces:** none new

- [ ] **Step 1: Write README** covering: install (`pip install -e .`), required `CDP_URL`, `crawl4ai-mcp serve`, log/connection JSON, `crawl4ai-mcp info`, `CONFIG_DIR`, tool list, explicit non-goals (Docker/search later), note that `skills` copy is independent

- [ ] **Step 2: Run full unit suite**

Run: `pytest -q`  
Expected: all PASS

- [ ] **Step 3: Manual smoke (if CDP available)** — start Chrome with remote debugging, `export CDP_URL=...`, `crawl4ai-mcp serve`, call `info`, optional MCP client convert of `https://example.com/` — if no CDP, document skip; do not claim success without evidence

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add crawl4ai-mcp README and usage"
```

---

## Spec coverage check

| Spec item | Task |
| --- | --- |
| Standalone repo / no skills edits | All |
| Streamable HTTP remote MCP | 6 |
| Bearer + auto key + log + connection JSON + CLI | 5–6 |
| `CDP_URL` env required, no fallback | 4, 6 |
| `convert_url` / `extract_summary` / `list_site_strategies` | 6 (+3/4) |
| YAML strategies + user `CONFIG_DIR` | 1–2 |
| Migrate WeChat etc. | 2 |
| Tests listed in spec | 1–6 |
| Docker out of v1 | 7 README only |

## Execution handoff

Plan complete after save. Prefer **Native** execution if you want one continuous session shipping the skeleton quickly; prefer **Subagent-driven** if you want per-task review gates on auth/CDP boundaries.
