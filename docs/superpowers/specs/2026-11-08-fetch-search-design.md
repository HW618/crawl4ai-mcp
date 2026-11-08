# fetch_url + web_search Design

Date: 2026-11-08  
Branch: `feat/v1`  
Status: Approved for implementation

## Goal

Add two MCP tools that expose more crawl4ai-local capabilities over the existing CloakBrowser CDP stack, without crawl4ai Cloud APIs.

## Tools

### `fetch_url`

- Inputs: `url`, `prefetch` (bool, default false), `timeout_sec` (default 45), `max_html_chars` (default 50000), `max_links` (default 50)
- Behavior: crawl via shared `CrawlerPool`; when `prefetch=True`, use crawl4ai prefetch mode (HTML + links, skip heavy markdown)
- Output JSON: `success`, `url`, `title`, `prefetch`, `html` (truncated), `links: {internal, external}` (each capped), `error`

### `web_search`

- Inputs: `query`, `engine` in `duckduckgo` | `bing` | `google` (default `duckduckgo`), `max_results` (default 8, max 20), `timeout_sec` (default 45)
- Behavior: build SERP URL for the engine, CDP-fetch the page, parse organic results with BeautifulSoup heuristics
- Output JSON: `engine`, `query`, `results: [{title, url, snippet}]`, `error`
- Failures (blocked SERP, empty parse): `success`-equivalent via non-empty `error`, empty `results` — never invent links

## Non-goals

- Deep crawl / `arun_many`
- Crawl4AI hosted `/search` or API keys
- Changing convert/summary contracts

## Testing

- Unit: SERP URL builders; HTML fixtures → parsed results per engine; fetch tool validates URL and respects max caps (mocked crawl)
- Live (optional): `fetch_url` on example.com; `web_search` DDG (may be flaky by network)
