from unittest.mock import AsyncMock, patch

import pytest

from crawl4ai_mcp.models import CrawlResult, SiteStrategy
from crawl4ai_mcp.tools import tool_convert_url, tool_extract_summary, tool_list_site_strategies


@pytest.mark.asyncio
async def test_convert_rejects_non_http_without_crawl():
    with patch("crawl4ai_mcp.tools.crawl_page", new_callable=AsyncMock) as crawl:
        text = await tool_convert_url(
            "ftp://example.com/a",
            strategies=[SiteStrategy(name="普通网页", source="builtin")],
        )
    crawl.assert_not_called()
    assert "http" in text.lower() or "无效" in text or "invalid" in text.lower()


@pytest.mark.asyncio
async def test_convert_reports_cdp_failure():
    strategies = [SiteStrategy(name="普通网页", source="builtin")]
    with patch(
        "crawl4ai_mcp.tools.crawl_page",
        new_callable=AsyncMock,
        return_value=CrawlResult(
            url="https://example.com/",
            success=False,
            error="CDP browser connection failed",
            strategy_name="普通网页",
        ),
    ):
        text = await tool_convert_url("https://example.com/", strategies=strategies)
    assert "cdp" in text.lower() or "connect" in text.lower()


@pytest.mark.asyncio
async def test_convert_passes_max_chars():
    strategies = [SiteStrategy(name="普通网页", source="builtin")]
    long_md = "word " * 5000
    with patch(
        "crawl4ai_mcp.tools.crawl_page",
        new_callable=AsyncMock,
        return_value=CrawlResult(
            url="https://example.com/",
            success=True,
            title="T",
            markdown=long_md,
            strategy_name="普通网页",
        ),
    ):
        text = await tool_convert_url(
            "https://example.com/",
            strategies=strategies,
            include_metadata=False,
            max_chars=200,
        )
    assert "内容已截断" in text
    assert len(text) < len(long_md)


def test_list_strategies():
    strategies = [
        SiteStrategy(name="A", domains=("a.com",), source="builtin"),
        SiteStrategy(name="B", domains=("b.com",), source="user"),
    ]
    text = tool_list_site_strategies(strategies)
    assert "A" in text and "builtin" in text
    assert "B" in text and "user" in text
