import asyncio
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
async def test_selector_probe_uses_one_navigation():
    strategy = SiteStrategy(
        name="知乎",
        domains=("zhihu.com",),
        css_selector="#missing",
        css_selector_fallbacks=("article.RichContent-inner",),
        source="builtin",
    )
    article = "fallback body " * 80
    html = (
        "<html><body><div id='a'>short</div>"
        f"<article class='RichContent-inner'><p>{article}</p></article></body></html>"
    )
    calls: list[str | None] = []

    async def fake_once(url, strategy, cdp_url, timeout_ms, verbose, css_selector):
        calls.append(css_selector)
        return CrawlResult(
            url=url,
            success=True,
            html=html,
            markdown="short",
            strategy_name=strategy.name,
        )

    with patch("crawl4ai_mcp.crawler._crawl_once", side_effect=fake_once):
        result = await crawl_page(
            "https://zhuanlan.zhihu.com/p/1",
            [strategy],
            cdp_url="http://127.0.0.1:9222",
        )
    assert calls == [None]
    assert result.success
    assert "fallback body" in result.markdown


@pytest.mark.asyncio
async def test_crawl_concurrency_cap_is_one_by_default():
    inflight = 0
    max_seen = 0

    async def fake_once(url, strategy, cdp_url, timeout_ms, verbose, css_selector):
        nonlocal inflight, max_seen
        inflight += 1
        max_seen = max(max_seen, inflight)
        await asyncio.sleep(0.05)
        inflight -= 1
        return CrawlResult(
            url=url,
            success=True,
            markdown="hello " * 80,
            strategy_name=strategy.name,
        )

    strategy = SiteStrategy(name="普通网页", source="builtin")
    with patch.dict("os.environ", {"CRAWL_MAX_CONCURRENCY": "1"}, clear=False):
        await reset_crawler_runtime()
        with patch("crawl4ai_mcp.crawler._crawl_once", side_effect=fake_once):
            await asyncio.gather(
                crawl_page("https://example.com/a", [strategy], cdp_url="http://cdp"),
                crawl_page("https://example.com/b", [strategy], cdp_url="http://cdp"),
            )
    assert max_seen == 1


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
    assert calls == [None]


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
