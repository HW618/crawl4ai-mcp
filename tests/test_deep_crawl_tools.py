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
