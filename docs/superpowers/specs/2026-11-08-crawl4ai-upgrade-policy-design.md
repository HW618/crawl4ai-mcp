# crawl4ai Upgrade Policy Design

Date: 2026-11-08  
Branch: `dev` / `feat/v1`  
Status: Approved for spec; pending user review of this file

## Goal

Make crawl4ai-mcp updates to the upstream `crawl4ai` library **reproducible**, **reviewable**, and **gated** by automated unit tests plus optional live CDP verification — without silently floating to a new crawl4ai on every Docker rebuild.

## Decisions

- Exact pin: `crawl4ai==X.Y.Z` in `pyproject.toml` (no lower-bound-only range)
- Both documentation and engineering automation
- CI: required unit tests; optional live Compose job when CDP is available (does not block merge when skipped)
- Dependabot (weekly) opens pin-bump PRs targeting `dev`

## Current baseline

| Component | Pin / note |
| --- | --- |
| crawl4ai | Start at `==0.9.5` (version in use at design time) |
| CloakBrowser | Compose still pins `cloakhq/cloakbrowser:0.6.5` (separate from this policy) |
| Install path | `Dockerfile` uses `pip install .` → inherits pyproject pin |

## Version policy

1. **Only change crawl4ai via an intentional pin bump** in `pyproject.toml`.
2. Docker image builds must not resolve a newer crawl4ai than the pin.
3. Document the active pin in `docs/operations.md` (Compatibility table) and keep `docs/upgrading-crawl4ai.md` as the human checklist.
4. MCP package version: bump only when this repo’s public tool behavior or API changes; a pure dependency pin bump may keep the same MCP version if tools are unchanged (note the crawl4ai pin in the PR body).

## Upgrade process (human / agent)

When Dependabot (or a manual PR) proposes `crawl4ai==NEW`:

1. Read upstream changelog / release notes for breaks affecting:
   - `AsyncWebCrawler` / `BrowserConfig(cdp_url=…)`
   - `CrawlerRunConfig` (`prefetch`, `deep_crawl_strategy`, markdown generator)
   - `crawl4ai.deep_crawling` strategy constructors / scorers
   - Result shapes: `.markdown`, `.links`, `.metadata["depth"]` / `["score"]`
2. Adapt adapters if needed (`crawler.py`, `deep_crawl.py`, search/fetch tools) in the **same** PR.
3. **Required:** `pytest` green.
4. **Recommended before merge to `dev`:** `docker compose up -d --build` + `scripts/integration_verify.py` + smoke `fetch_url` / `web_search` / `deep_crawl` / `crawl_many`.
5. If unfixable: leave pin unchanged, close or pause the Dependabot PR, open a tracking issue.

## Automation

### Dependabot

- Add `.github/dependabot.yml`
- Ecosystem: `pip` at `/`
- Interval: weekly
- Target branch: `dev`
- Prefer limiting noise to `crawl4ai` (allow / ignore rules as GitHub Dependabot supports)

### Required CI

- Add `.github/workflows/ci.yml`
- Triggers: pull_request + push to `dev`, `master`, `feat/**`
- Steps: checkout → setup Python 3.12 → `pip install -e '.[dev]'` → `pytest -q`
- Required check for merging into `dev`

### Optional live CI

- Add `.github/workflows/live.yml`
- Triggers: `workflow_dispatch`; optional schedule
- Gate: only run meaningful steps when `vars.LIVE_CDP_AVAILABLE == 'true'` (or equivalent repo variable); otherwise no-op success / skip
- Steps when enabled: Compose up (CloakBrowser + MCP) → `integration_verify.py`
- **Not** a required status check (matches decision B)

## Docs deliverables

| Path | Content |
| --- | --- |
| `docs/upgrading-crawl4ai.md` | Checklist + compat surface list + “hold pin” path |
| `docs/operations.md` | Short Compatibility row (crawl4ai pin, Cloak tag) |
| `README.md` | Link to upgrading doc under Tests / ops |

## Non-goals

- Locking the full transitive dependency tree
- Auto-merge Dependabot PRs
- Coupling CloakBrowser major upgrades into the same bot
- Making live CDP a hard merge gate on GitHub-hosted runners without CDP

## Testing this policy itself

- After pin change to `==0.9.5`, unit suite still passes locally / in CI
- Dependabot config validates (YAML) and opens PRs only for intended packages once enabled
- Live workflow skips cleanly when `LIVE_CDP_AVAILABLE` is unset

## Self-review

- No TBD placeholders in process steps
- Pin strategy matches user choice A; CI gate matches B; scope includes docs + automation (C)
- CloakBrowser kept out of crawl4ai bump bot to avoid license/key coupling
