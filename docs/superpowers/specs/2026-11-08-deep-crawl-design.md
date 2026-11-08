# deep_crawl + crawl_many Design

Date: 2026-11-08  
Branch: `feat/v1`  
Status: Approved for spec; pending user review of this file

## Goal

Expose crawl4ai deep crawling and multi-URL batch crawling over the existing CloakBrowser CDP stack, returning per-page Markdown via the current convert path. No Crawl4AI Cloud APIs; no async job store.

## Decisions (from brainstorming)

- Both seed deep-crawl **and** explicit URL batch crawl
- Per-page Markdown (same converter as `convert_url`)
- Strategies: `bfs` | `dfs` | `best_first` (optional keyword scorer)
- Caps: default `max_depth=2`, `max_pages=50`; hard ceilings depth≤5, pages≤100; batch ≤100 URLs
- Two MCP tools (not a single mode-switched tool)

## Tools

### `deep_crawl`

| Input | Default | Notes |
| --- | --- | --- |
| `url` | required | `http(s)` only |
| `strategy` | `bfs` | `bfs` \| `dfs` \| `best_first` |
| `max_depth` | `2` | clamped to `[0, 5]` |
| `max_pages` | `50` | clamped to `[1, 100]` |
| `include_external` | `false` | passed to crawl4ai strategy |
| `keywords` | `[]` | optional; builds `KeywordRelevanceScorer` when non-empty |
| `timeout_sec` | `45` | per-page page timeout |
| `max_chars` | `null` | optional per-page markdown cap |

Behavior:

1. Validate URL; clamp depth/pages; reject unknown strategy with JSON error
2. Build `BFSDeepCrawlStrategy` / `DFSDeepCrawlStrategy` / `BestFirstCrawlingStrategy` with optional scorer
3. Run via shared `CrawlerPool` + `CrawlerRunConfig(deep_crawl_strategy=…)`
4. Map each crawl4ai hit → convert with site strategies when URL matches
5. Return one JSON string

Output:

```json
{
  "pages": [
    {
      "url": "...",
      "title": "...",
      "depth": 0,
      "score": null,
      "markdown": "...",
      "success": true,
      "error": "",
      "strategy_name": "普通网页"
    }
  ],
  "stats": {"crawled": 1, "succeeded": 1, "failed": 0},
  "error": ""
}
```

### `crawl_many`

| Input | Default | Notes |
| --- | --- | --- |
| `urls` | required | list; empty → error; len > 100 → error |
| `timeout_sec` | `45` | per-page |
| `max_chars` | `null` | optional markdown cap |

Behavior: crawl each URL without deep-link discovery (`arun_many` or sequential pool `arun`), convert successes, preserve input order in `pages`. Same output shape; `depth`/`score` omitted or null.

## Architecture

- `crawler.py`: `deep_crawl_pages`, `crawl_many_pages` — CDP-only; reuse pool; invalidate on browser errors
- `tools.py`: validation, clamps, convert, JSON assembly
- `server.py`: register both tools

Partial failure is success at the tool level: pages may mix `success` true/false; top-level `error` only for input/config/CDP hard failures that produce no usable run.

## Non-goals

- Resume / cancel / `on_state_change` persistence
- Rich FilterChain UI (domain/pattern filters beyond `include_external`)
- Async start/poll job API
- Streaming MCP responses
- Changing convert/summary/fetch/search contracts

## Testing

- Unit: clamps, unknown strategy, empty/oversized URL list, mocked multi-page → markdown + stats, strategy builder (+ keywords → scorer)
- Live (optional): small `crawl_many`; `deep_crawl` with `max_depth=1`, `max_pages=3` under Compose — not CI-blocking

## Self-review

- No placeholders or TBD left in tool contracts
- Caps consistent with user choice C (loose)
- Scope limited to two tools; no conflict with existing `fetch_url` / `web_search`
- Output never invents pages
