# Operations and verification

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

Recorded by `scripts/integration_verify.py` on 2026-11-08:

| Case | Latency |
| --- | --- |
| MCP initialize / list strategies | ~2 ms |
| `convert_url` https://example.com/ (1st / 2nd) | ~1000 ms / ~950 ms |
| `extract_summary` example.com | ~940 ms |
| `convert_url` Wikipedia “Web scraping” | ~2100 ms (body truncated at 50k chars) |
| `convert_url` IANA reserved domains | ~2100 ms |
| `convert_url` juejin.cn (strategy 掘金) | ~30 s then crawl error from this network |

## Performance headroom

Highest-impact improvements (not implemented yet):

1. **Reuse CDP / `AsyncWebCrawler` across tool calls** — today each crawl opens and closes a crawler context (`async with AsyncWebCrawler(...)`), so every request pays CDP attach cost (~similar 1st vs 2nd example.com times). A process-wide pool or long-lived connection would cut simple-page latency.
2. **Smarter selector fallbacks** — strategies with several `css_selector_fallbacks` can run multiple full navigations; short-circuit on browser errors and/or probe selectors without full reload.
3. **Optional HTTP cache** — `CacheMode.BYPASS` always; a short TTL cache helps repeated URLs in agent loops.
4. **Configurable `max_chars` on the MCP tool** — Wikipedia hits the 50k converter cap; exposing `max_chars` avoids wasted transfer when clients want less.
5. **Parallelism limits** — CloakBrowser 0.6.5 / free tiers are session-limited; document concurrency expectations before adding a request queue.

Lower priority: suppress Crawl4AI cloud banner via `CRAWL4AI_NO_CLOUD_NOTICE=1` (already set in Compose).
