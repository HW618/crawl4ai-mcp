# Upgrading crawl4ai

This project **exact-pins** the upstream library in `pyproject.toml`:

```toml
crawl4ai==0.9.5
```

Do not use `crawl4ai>=…`. Docker builds (`pip install .`) inherit the pin so images stay reproducible.

CloakBrowser (`cloakhq/cloakbrowser:0.6.5` in Compose) is upgraded separately and is not part of the crawl4ai Dependabot allowlist.

## When a new crawl4ai version appears

Dependabot opens a weekly PR against `dev` that bumps the pin (dependency name `crawl4ai` only). You can also bump manually.

### Checklist

1. **Changelog / release notes** — look for breaks in:
   - `AsyncWebCrawler` / `BrowserConfig(cdp_url=…)`
   - `CrawlerRunConfig` (`prefetch`, `deep_crawl_strategy`, markdown generator)
   - `crawl4ai.deep_crawling` strategy constructors / scorers
   - Result shapes: `.markdown`, `.links`, `.metadata["depth"]` / `["score"]`
2. **Adapt adapters** in the same PR if needed (`crawler.py`, `deep_crawl.py`, tools).
3. **Required:** `pytest -q` green (also enforced by `.github/workflows/ci.yml`).
4. **Recommended before merging to `dev`:**
   ```bash
   docker compose up -d --build
   python3 scripts/integration_verify.py
   ```
   Plus smoke `fetch_url`, `web_search`, `deep_crawl`, and `crawl_many` against the live MCP.
5. **If unfixable:** keep the previous pin, close or pause the Dependabot PR, open a tracking issue.

Optional GitHub live job (`.github/workflows/live.yml`) runs only when repository variable `LIVE_CDP_AVAILABLE` is `true`. It is **not** a required merge check; without that variable the workflow skips with exit 0.

## After merge

Rebuild and redeploy Compose (or reinstall the editable package) so the running MCP picks up the new pin.
