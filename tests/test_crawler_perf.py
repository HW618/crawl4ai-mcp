from unittest.mock import MagicMock, patch

import pytest

from crawl4ai_mcp.crawler import (
    CrawlerPool,
    crawl_page,
    reset_crawler_runtime,
)
from crawl4ai_mcp.models import CrawlResult, SiteStrategy


@pytest.fixture(autouse=True)
async def _reset_runtime():
    await reset_crawler_runtime()
    yield
    await reset_crawler_runtime()


@pytest.mark.asyncio
async def test_selector_fallback_stops_after_browser_error():
    strategy = SiteStrategy(
        name="Demo",
        domains=("example.com",),
        css_selector="#a",
        css_selector_fallbacks=("#b", "#c"),
        source="builtin",
    )
    calls: list[str | None] = []

    async def fake_once(url, strategy, cdp_url, timeout_ms, verbose, css_selector):
        calls.append(css_selector)
        return CrawlResult(
            url=url,
            success=False,
            error="CDP browser connection failed",
            error_kind="browser",
            strategy_name=strategy.name,
        )

    with patch("crawl4ai_mcp.crawler._crawl_once", side_effect=fake_once):
        result = await crawl_page(
            "https://example.com/x",
            [strategy],
            cdp_url="http://127.0.0.1:9222",
        )
    assert result.error_kind == "browser"
    assert calls == ["#a"]


@pytest.mark.asyncio
async def test_crawl_cache_reuses_result():
    strategy = SiteStrategy(name="普通网页", domains=(), source="builtin")
    calls = {"n": 0}

    async def fake_once(url, strategy, cdp_url, timeout_ms, verbose, css_selector):
        calls["n"] += 1
        return CrawlResult(
            url=url,
            success=True,
            markdown="hello world " * 50,
            strategy_name=strategy.name,
        )

    with patch("crawl4ai_mcp.crawler._crawl_once", side_effect=fake_once):
        with patch.dict("os.environ", {"CRAWL_CACHE_TTL_SEC": "60"}, clear=False):
            await reset_crawler_runtime()
            r1 = await crawl_page("https://example.com/", [strategy], cdp_url="http://cdp")
            r2 = await crawl_page("https://example.com/", [strategy], cdp_url="http://cdp")
    assert r1.success and r2.success
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_pool_reuses_started_crawler():
    starts = {"n": 0}

    class FakeCrawler:
        def __init__(self, *args, **kwargs):
            pass

        async def start(self):
            starts["n"] += 1
            return self

        async def close(self):
            return None

        async def arun(self, *args, **kwargs):
            return MagicMock(
                success=True,
                html="<p>x</p>",
                markdown=MagicMock(raw_markdown="y" * 500),
                metadata={},
            )

    pool = CrawlerPool()
    with patch("crawl4ai_mcp.crawler.AsyncWebCrawler", FakeCrawler):
        c1 = await pool.get("http://cdp")
        c2 = await pool.get("http://cdp")
        await pool.close()
    assert c1 is c2
    assert starts["n"] == 1
