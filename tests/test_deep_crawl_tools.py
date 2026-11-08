import json
from unittest.mock import AsyncMock, patch

import pytest

from crawl4ai_mcp.models import CrawlResult, SiteStrategy
from crawl4ai_mcp.tools import tool_crawl_many, tool_deep_crawl


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
    # convert_to_markdown may exceed max_chars by appending a truncation footer
    assert "内容已截断" in data["pages"][0]["markdown"] or len(data["pages"][0]["markdown"]) <= 20
    assert data["pages"][1]["depth"] == 1


@pytest.mark.asyncio
async def test_deep_crawl_hard_error():
    strategies = [SiteStrategy(name="普通网页", source="builtin")]
    with patch(
        "crawl4ai_mcp.tools.deep_crawl_pages",
        new_callable=AsyncMock,
        return_value=([], "CDP browser connection failed"),
    ):
        data = json.loads(await tool_deep_crawl("https://example.com/", strategies=strategies))
    assert data["pages"] == []
    assert "CDP" in data["error"] or "failed" in data["error"].lower()


@pytest.mark.asyncio
async def test_crawl_many_rejects_empty_and_oversized():
    strategies = [SiteStrategy(name="普通网页", source="builtin")]
    empty = json.loads(await tool_crawl_many([], strategies=strategies))
    assert empty["pages"] == [] and empty["error"]
    big = json.loads(
        await tool_crawl_many([f"https://example.com/{i}" for i in range(101)], strategies=strategies)
    )
    assert big["pages"] == [] and ("100" in big["error"] or "max" in big["error"].lower())


@pytest.mark.asyncio
async def test_crawl_many_preserves_order_and_failures():
    strategies = [SiteStrategy(name="普通网页", source="builtin")]
    results = [
        CrawlResult(url="https://example.com/1", success=True, markdown="# 1"),
        CrawlResult(url="https://example.com/2", success=False, error="boom"),
    ]
    with patch(
        "crawl4ai_mcp.tools.crawl_many_pages",
        new_callable=AsyncMock,
        return_value=(results, ""),
    ):
        data = json.loads(
            await tool_crawl_many(
                ["https://example.com/1", "https://example.com/2"], strategies=strategies
            )
        )
    assert data["stats"] == {"crawled": 2, "succeeded": 1, "failed": 1}
    assert data["pages"][0]["success"] is True
    assert data["pages"][1]["success"] is False


@pytest.mark.asyncio
async def test_crawl_many_pages_keeps_remaining_after_browser_error():
    from crawl4ai_mcp.crawler import crawl_many_pages

    strategies = [SiteStrategy(name="普通网页", source="builtin")]
    urls = ["https://example.com/1", "https://example.com/2", "https://example.com/3"]

    async def fake_crawl(url, *_a, **_k):
        if url.endswith("/1"):
            return CrawlResult(url=url, success=True, markdown="# 1")
        if url.endswith("/2"):
            return CrawlResult(
                url=url, success=False, error="connection reset", error_kind="browser"
            )
        raise AssertionError("should not crawl after browser failure without stubbing remainder")

    with patch("crawl4ai_mcp.crawler.crawl_page", new=AsyncMock(side_effect=fake_crawl)):
        with patch("crawl4ai_mcp.crawler._pool.invalidate", new_callable=AsyncMock) as inv:
            results, err = await crawl_many_pages(urls, strategies, cdp_url="http://cdp")
    assert inv.await_count == 1
    assert len(results) == 3
    assert results[0].success is True
    assert results[1].success is False
    assert results[2].success is False
    assert results[2].error
    assert err == ""


@pytest.mark.asyncio
async def test_deep_crawl_pages_keeps_all_hits_on_browserish_page():
    from types import SimpleNamespace

    from crawl4ai_mcp.crawler import deep_crawl_pages

    strategies = [
        SiteStrategy(name="知乎", domains=("zhihu.com",), title_suffixes=(" - 知乎",), css_selector=".Post")
    ]
    items = [
        SimpleNamespace(
            url="https://www.zhihu.com/a",
            success=True,
            html="<p>x</p>",
            markdown=SimpleNamespace(raw_markdown="# A - 知乎\n\nbody"),
            metadata={"title": "A - 知乎", "depth": 0},
            error_message=None,
        ),
        SimpleNamespace(
            url="https://www.zhihu.com/b",
            success=False,
            html="",
            markdown=None,
            metadata={"depth": 1},
            error_message="ERR_CONNECTION_RESET",
        ),
        SimpleNamespace(
            url="https://www.zhihu.com/c",
            success=True,
            html="<p>y</p>",
            markdown=SimpleNamespace(raw_markdown="# C - 知乎\n\nbody"),
            metadata={"title": "C - 知乎", "depth": 1},
            error_message=None,
        ),
    ]
    crawler = SimpleNamespace(arun=AsyncMock(return_value=items))
    with patch("crawl4ai_mcp.crawler.assert_cdp_ready", return_value="http://cdp"):
        with patch("crawl4ai_mcp.crawler._pool.get", new_callable=AsyncMock, return_value=crawler):
            with patch("crawl4ai_mcp.crawler._pool.invalidate", new_callable=AsyncMock) as inv:
                hits, err = await deep_crawl_pages(
                    "https://www.zhihu.com/a", strategies, strategy="bfs", max_depth=1, max_pages=5
                )
    assert inv.await_count == 1
    assert err == ""
    assert len(hits) == 3
    assert hits[0][0].title == "A"
    assert hits[1][0].success is False
    assert hits[2][0].success is True


def test_deep_run_config_uses_seed_strategy_selector():
    from crawl4ai_mcp.crawler import build_deep_run_config
    from crawl4ai_mcp.models import SiteStrategy

    strategy = SiteStrategy(
        name="微信",
        css_selector="#js_content",
        wait_for="css:#js_content",
        excluded_selector=".qr",
        js_snippets=["() => {}"],
    )
    cfg = build_deep_run_config(strategy, deep_strategy=object(), timeout_ms=1000)
    assert cfg.css_selector == "#js_content"
    assert cfg.wait_for == "css:#js_content"
    assert cfg.excluded_selector == ".qr"
