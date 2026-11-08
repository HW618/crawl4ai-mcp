# Operations and verification

## Compatibility

| Component | Version / pin |
| --- | --- |
| crawl4ai (Python) | `==0.9.5` in `pyproject.toml` |
| CloakBrowser | `cloakhq/cloakbrowser:0.6.5` (Compose) |

See [upgrading-crawl4ai.md](upgrading-crawl4ai.md) for the pin-bump process.

## Stack

| Service | Image / build | Host ports |
| --- | --- | --- |
| `cloakbrowser` | `cloakhq/cloakbrowser:0.6.5` (`cloakserve`, keyless) | `127.0.0.1:9222` |
| `mcp` | build from this repo | `127.0.0.1:8000` → `/mcp` |

Internal CDP URL used by MCP: `http://cloakbrowser:9222`.

## Start / stop

```bash
docker compose up -d --build
docker compose logs -f mcp          # copy API key from "API key: …"
docker compose down
```

`crawl4ai-mcp info` against the data volume:

```bash
docker compose run --rm -e CRAWL4AI_MCP_DATA_DIR=/data mcp crawl4ai-mcp info
```

## Live integration verify

With the stack up:

```bash
python3 scripts/integration_verify.py
# or:
# API_KEY=… MCP_URL=http://127.0.0.1:8000/mcp python3 scripts/integration_verify.py
```

The script checks CDP `/json/version`, Bearer auth negatives, MCP initialize, `list_site_strategies`, invalid URL handling, `convert_url` / `extract_summary` on public pages, and a CN-site strategy route (may fail extraction from some networks; timeout is treated as an environment limit when it happens).

Unit tests (no browser):

```bash
.venv/bin/python -m pytest -q
```

## Observed timings (this host, CloakBrowser 0.6.5)

After the performance work (shared CDP crawler + TTL cache + browser-error short-circuit), `scripts/integration_verify.py` on 2026-11-08:

| Case | Latency |
| --- | --- |
| MCP initialize / list strategies | ~3–4 ms |
| `convert_url` https://example.com/ (1st / 2nd) | ~1137 ms / **~3 ms** (cache hit) |
| `extract_summary` example.com (after convert) | **~3 ms** (same crawl cache) |
| `convert_url` Wikipedia “Web scraping” | ~1315 ms (body still truncated at default 50k; pass `max_chars`) |
| `convert_url` IANA reserved domains | ~438 ms |
| `convert_url` juejin.cn (strategy 掘金) | may timeout from this network |

Baseline before these changes: example.com 1st/2nd were both ~1 s (no session reuse, no crawl cache).

## Performance features

1. **Shared CDP crawler** — process-wide `CrawlerPool` keeps one started `AsyncWebCrawler` per `CDP_URL`; browser-level failures invalidate the pool so the next call reconnects.
2. **Selector fallback short-circuit** — if a crawl fails with `error_kind=browser`, remaining `css_selector_fallbacks` are skipped.
3. **TTL crawl cache** — successful `CrawlResult`s cached in-process (`CRAWL_CACHE_TTL_SEC`, default `60`; `0` disables). Repeated agent converts/summaries of the same URL reuse the cached crawl.
4. **`max_chars` on `convert_url`** — optional MCP tool argument; omit to keep the converter default (50k).

Still optional later: request queue / concurrency caps for CloakBrowser session limits; richer selector probing without full re-navigation.

Compose already sets `CRAWL4AI_NO_CLOUD_NOTICE=1` and `CRAWL_CACHE_TTL_SEC`.
