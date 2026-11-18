# deep_crawl + crawl_many Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add MCP tools `deep_crawl` and `crawl_many` that return per-page Markdown over the shared CDP crawler pool.

**Architecture:** Pure helpers build crawl4ai deep strategies and clamp inputs; `crawler.py` runs deep/`arun_many` on `CrawlerPool` and maps hits to `CrawlResult` (+ depth/score); `tools.py` converts each page and emits the spec JSON; `server.py` registers both tools.

**Tech Stack:** Python 3.11+, crawl4ai (`BFSDeepCrawlStrategy` / `DFSDeepCrawlStrategy` / `BestFirstCrawlingStrategy`, `KeywordRelevanceScorer`), existing `convert_to_markdown`, pytest + AsyncMock.

**Spec:** `docs/superpowers/specs/2026-11-08-deep-crawl-design.md`

## Global Constraints

- Caps: default `max_depth=2`, `max_pages=50`; clamp depth to `[0, 5]`, pages to `[1, 100]`; batch URL list hard max `100`
- Strategies: `bfs` | `dfs` | `best_first` only; unknown → JSON `error`, empty `pages`
- CDP-only via existing pool; invalidate pool on browser errors
- Per-page Markdown via `convert_to_markdown` (same path as `convert_url`)
- Never invent pages; partial failures stay in `pages` with `success=false`
- Output shape: `{pages, stats: {crawled, succeeded, failed}, error}`

## Review Focus

- Oversized `urls` (101) → top-level error, no crawl — Task 3 test
- `keywords` empty on `best_first` still builds strategy (scorer optional) — Task 1 test
- Deep-crawl browser failure mid-run → pool invalidate + top-level or page errors, no hang — Task 2 test (mock raise)
- `max_chars` applied per page markdown — Task 2/3 tool tests
- `include_external=true` passed through to strategy ctor — Task 1 test

---

## File structure

| File | Responsibility |
| --- | --- |
| Create `src/crawl4ai_mcp/deep_crawl.py` | Strategy name → crawl4ai strategy; clamp helpers; page-row typing helpers |
| Modify `src/crawl4ai_mcp/crawler.py` | `deep_crawl_pages`, `crawl_many_pages` |
| Modify `src/crawl4ai_mcp/tools.py` | `tool_deep_crawl`, `tool_crawl_many` |
| Modify `src/crawl4ai_mcp/server.py` | Register MCP tools |
| Modify `README.md` | Document tools; drop deep-crawl from non-goals |
| Create `tests/test_deep_crawl_strategy.py` | Builder + clamps |
| Create `tests/test_deep_crawl_tools.py` | Tool JSON with mocks |

---

### Task 1: Strategy builder + clamps

**Files:**
- Create: `src/crawl4ai_mcp/deep_crawl.py`
- Test: `tests/test_deep_crawl_strategy.py`

**Interfaces:**
- Produces:
  - `SUPPORTED_DEEP_STRATEGIES: tuple[str, ...] = ("bfs", "dfs", "best_first")`
  - `clamp_max_depth(value: int | None) -> int`  # default 2, clamp [0, 5]
  - `clamp_max_pages(value: int | None) -> int`  # default 50, clamp [1, 100]
  - `build_deep_strategy(strategy: str, *, max_depth: int, max_pages: int, include_external: bool = False, keywords: list[str] | None = None) -> object`  # raises `ValueError` on unknown name
  - `MAX_BATCH_URLS: int = 100`

- [ ] **Step 1: Write failing tests** in `tests/test_deep_crawl_strategy.py`

```python
from crawl4ai.deep_crawling import (
    BFSDeepCrawlStrategy,
    BestFirstCrawlingStrategy,
    DFSDeepCrawlStrategy,
)
from crawl4ai_mcp.deep_crawl import (
    build_deep_strategy,
    clamp_max_depth,
    clamp_max_pages,
)


def test_clamps():
    assert clamp_max_depth(None) == 2
    assert clamp_max_depth(9) == 5
    assert clamp_max_depth(-1) == 0
    assert clamp_max_pages(None) == 50
    assert clamp_max_pages(0) == 1
    assert clamp_max_pages(200) == 100


def test_build_bfs_dfs_best_first():
    assert isinstance(build_deep_strategy("bfs", max_depth=1, max_pages=3), BFSDeepCrawlStrategy)
    assert isinstance(build_deep_strategy("dfs", max_depth=1, max_pages=3), DFSDeepCrawlStrategy)
    s = build_deep_strategy("best_first", max_depth=1, max_pages=3, keywords=["a"])
    assert isinstance(s, BestFirstCrawlingStrategy)


def test_best_first_without_keywords_ok():
    assert isinstance(
        build_deep_strategy("best_first", max_depth=1, max_pages=3, keywords=[]),
        BestFirstCrawlingStrategy,
    )


def test_include_external_passed():
    s = build_deep_strategy("bfs", max_depth=1, max_pages=2, include_external=True)
    assert s.include_external is True


def test_unknown_strategy_raises():
    import pytest
    with pytest.raises(ValueError):
        build_deep_strategy("random", max_depth=1, max_pages=1)
```

- [ ] **Step 2: Run tests — expect FAIL** (`ModuleNotFoundError: crawl4ai_mcp.deep_crawl`)

Run: `.venv/bin/python -m pytest tests/test_deep_crawl_strategy.py -q`

- [ ] **Step 3: Implement** `src/crawl4ai_mcp/deep_crawl.py` with the Interfaces signatures; map names to crawl4ai classes; attach `KeywordRelevanceScorer(keywords=…)` only when `keywords` non-empty

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit** `feat: add deep crawl strategy builder and clamps`

---

### Task 2: `deep_crawl` tool (mocked crawl)

**Files:**
- Modify: `src/crawl4ai_mcp/crawler.py` — add `deep_crawl_pages`
- Modify: `src/crawl4ai_mcp/tools.py` — add `tool_deep_crawl`
- Test: `tests/test_deep_crawl_tools.py`

**Interfaces:**
- Consumes: `build_deep_strategy`, clamps from Task 1; `convert_to_markdown`; `CrawlerPool`
- Produces:
  - `async def deep_crawl_pages(url: str, strategies: list[SiteStrategy], *, strategy: str = "bfs", max_depth: int = 2, max_pages: int = 50, include_external: bool = False, keywords: list[str] | None = None, timeout_ms: int = 45000, cdp_url: str | None = None) -> tuple[list[tuple[CrawlResult, int | None, float | None]], str]`  
    # returns `(hits, error)` where each hit is `(CrawlResult, depth, score)`; `error` non-empty on hard failure
  - `async def tool_deep_crawl(url: str, *, strategies: list[SiteStrategy], strategy: str = "bfs", max_depth: int = 2, max_pages: int = 50, include_external: bool = False, keywords: list[str] | None = None, timeout_sec: int = 45, max_chars: int | None = None, cdp_url: str | None = None) -> str`

Implementation notes (not a full body):
- Prefer `crawler.arun(url, config=CrawlerRunConfig(deep_crawl_strategy=..., page_timeout=..., cache_mode=BYPASS, markdown_generator=build_markdown_generator()))`; normalize return to a list (single result, list, or async-iter).
- Read `depth` / `score` from crawl4ai `metadata` when present (`depth`, `score`, or nested deep-crawl keys); else `None`.
- Map each hit with same HTML/markdown/title extraction patterns as `fetch_page` / `_crawl_once` (success = non-empty markdown after extract, or mark page failed).
- Tools always JSON-encode; on bad URL / unknown strategy set `error` and empty `pages`.

- [ ] **Step 1: Write failing tests** in `tests/test_deep_crawl_tools.py`

```python
import json
from unittest.mock import AsyncMock, patch
import pytest
from crawl4ai_mcp.models import CrawlResult, SiteStrategy
from crawl4ai_mcp.tools import tool_deep_crawl


@pytest.mark.asyncio
async def test_deep_crawl_rejects_bad_url():
    text = await tool_deep_crawl("ftp://x", strategies=[SiteStrategy(name="普通网页", source="builtin")])
    data = json.loads(text)
    assert data["pages"] == []
    assert data["error"]


@pytest.mark.asyncio
async def test_deep_crawl_unknown_strategy():
    text = await tool_deep_crawl(
        "https://example.com/",
        strategies=[SiteStrategy(name="普通网页", source="builtin")],
        strategy="yahoo",
    )
    data = json.loads(text)
    assert data["pages"] == []
    assert "strategy" in data["error"].lower() or "yahoo" in data["error"].lower()


@pytest.mark.asyncio
async def test_deep_crawl_markdown_pages_and_stats():
    strategies = [SiteStrategy(name="普通网页", source="builtin")]
    hits = [
        (CrawlResult(url="https://example.com/", success=True, title="A", markdown="# A\n\nHello"), 0, None),
        (CrawlResult(url="https://example.com/b", success=True, title="B", markdown="# B\n\nWorld"), 1, 0.5),
    ]
    with patch("crawl4ai_mcp.tools.deep_crawl_pages", new_callable=AsyncMock, return_value=(hits, "")):
        text = await tool_deep_crawl("https://example.com/", strategies=strategies, max_chars=20)
    data = json.loads(text)
    assert data["stats"]["crawled"] == 2
    assert data["stats"]["succeeded"] == 2
    assert data["pages"][0]["markdown"]
    assert len(data["pages"][0]["markdown"]) <= 20 or "strategy:" in data["pages"][0]["markdown"]
    assert data["pages"][1]["depth"] == 1
```

Also add: mock `deep_crawl_pages` raising/returning browser error → JSON `error` or failed pages; assert no crash.

- [ ] **Step 2: Run — expect FAIL** (import / missing symbol)

Run: `.venv/bin/python -m pytest tests/test_deep_crawl_tools.py -q`

- [ ] **Step 3: Implement** `deep_crawl_pages` + `tool_deep_crawl`

- [ ] **Step 4: Run — expect PASS** for Task 2 tests

- [ ] **Step 5: Commit** `feat: add deep_crawl MCP tool`

---

### Task 3: `crawl_many` tool

**Files:**
- Modify: `src/crawl4ai_mcp/crawler.py` — add `crawl_many_pages`
- Modify: `src/crawl4ai_mcp/tools.py` — add `tool_crawl_many`
- Modify: `tests/test_deep_crawl_tools.py`

**Interfaces:**
- Produces:
  - `async def crawl_many_pages(urls: list[str], strategies: list[SiteStrategy], *, timeout_ms: int = 45000, cdp_url: str | None = None) -> tuple[list[CrawlResult], str]`
  - `async def tool_crawl_many(urls: list[str], *, strategies: list[SiteStrategy], timeout_sec: int = 45, max_chars: int | None = None, cdp_url: str | None = None) -> str`

Notes: prefer existing `crawl_page` per URL (preserves site-strategy fallbacks + cache) in input order; empty list → error; `len(urls) > MAX_BATCH_URLS` → error without crawling. Do **not** attach `deep_crawl_strategy`.

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_crawl_many_rejects_empty_and_oversized():
    strategies = [SiteStrategy(name="普通网页", source="builtin")]
    empty = json.loads(await tool_crawl_many([], strategies=strategies))
    assert empty["pages"] == [] and empty["error"]
    big = json.loads(await tool_crawl_many([f"https://example.com/{i}" for i in range(101)], strategies=strategies))
    assert big["pages"] == [] and ("100" in big["error"] or "max" in big["error"].lower())


@pytest.mark.asyncio
async def test_crawl_many_preserves_order_and_failures():
    strategies = [SiteStrategy(name="普通网页", source="builtin")]
    results = [
        CrawlResult(url="https://example.com/1", success=True, markdown="# 1"),
        CrawlResult(url="https://example.com/2", success=False, error="boom"),
    ]
    with patch("crawl4ai_mcp.tools.crawl_many_pages", new_callable=AsyncMock, return_value=(results, "")):
        data = json.loads(await tool_crawl_many(
            ["https://example.com/1", "https://example.com/2"], strategies=strategies
        ))
    assert data["stats"] == {"crawled": 2, "succeeded": 1, "failed": 1}
    assert data["pages"][0]["success"] is True
    assert data["pages"][1]["success"] is False
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement** `crawl_many_pages` + `tool_crawl_many`

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_deep_crawl_strategy.py tests/test_deep_crawl_tools.py -q` — expect PASS

- [ ] **Step 5: Commit** `feat: add crawl_many MCP tool`

---

### Task 4: Register tools + docs + full suite

**Files:**
- Modify: `src/crawl4ai_mcp/server.py` — register `deep_crawl`, `crawl_many`
- Modify: `README.md` — tools table; remove deep crawl from Non-goals
- Optional: one-line note in `docs/operations.md` if a live checklist exists

- [ ] **Step 1: Wire** server tools with the same parameter defaults as the spec

- [ ] **Step 2: Update README** tool table rows for `deep_crawl` and `crawl_many`

- [ ] **Step 3: Run full suite**

Run: `.venv/bin/python -m pytest -q`  
Expected: all pass (prior suite + new tests)

- [ ] **Step 4: Commit** `feat: expose deep_crawl and crawl_many on MCP server`

- [ ] **Step 5: Push** `git push -u origin HEAD` on `feat/v1`

---

## Spec coverage (self-review)

| Spec item | Task |
| --- | --- |
| `deep_crawl` inputs/caps/strategies/keywords | 1, 2 |
| `crawl_many` + max 100 | 3 |
| Markdown convert path | 2, 3 |
| JSON pages/stats/error | 2, 3 |
| CDP pool / browser invalidate | 2 (crawler impl) |
| Non-goals (no jobs/filters UI) | respected — no tasks |
| README / MCP registration | 4 |
