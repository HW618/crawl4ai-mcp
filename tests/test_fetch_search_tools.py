import json
from unittest.mock import AsyncMock, patch

import pytest

from crawl4ai_mcp.models import CrawlResult, SiteStrategy
from crawl4ai_mcp.tools import tool_fetch_url, tool_web_search


@pytest.mark.asyncio
async def test_fetch_rejects_bad_url():
    text = await tool_fetch_url(
        "ftp://x",
        strategies=[SiteStrategy(name="普通网页", source="builtin")],
    )
    data = json.loads(text)
    assert data["success"] is False
    assert "http" in data["error"].lower() or "无效" in data["error"]


@pytest.mark.asyncio
async def test_fetch_url_caps_html_and_links():
    strategies = [SiteStrategy(name="普通网页", source="builtin")]
    fake = CrawlResult(
        url="https://example.com/",
        success=True,
        title="Example",
        html="H" * 1000,
        markdown="",
        strategy_name="普通网页",
    )
    with patch(
        "crawl4ai_mcp.tools.fetch_page",
        new_callable=AsyncMock,
        return_value=(
            fake,
            {
                "internal": [{"href": f"https://example.com/{i}", "text": str(i)} for i in range(20)],
                "external": [{"href": f"https://out.example/{i}", "text": str(i)} for i in range(20)],
            },
        ),
    ):
        text = await tool_fetch_url(
            "https://example.com/",
            strategies=strategies,
            max_html_chars=50,
            max_links=3,
        )
    data = json.loads(text)
    assert data["success"] is True
    assert len(data["html"]) <= 50
    assert len(data["links"]["internal"]) == 3
    assert len(data["links"]["external"]) == 3


@pytest.mark.asyncio
async def test_web_search_rejects_unknown_engine():
    text = await tool_web_search(
        "query",
        strategies=[SiteStrategy(name="普通网页", source="builtin")],
        engine="yahoo",
    )
    data = json.loads(text)
    assert data["results"] == []
    assert "engine" in data["error"].lower() or "yahoo" in data["error"].lower()


@pytest.mark.asyncio
async def test_web_search_parses_mocked_serp():
    strategies = [SiteStrategy(name="普通网页", source="builtin")]
    html = """
    <div class="result results_links">
      <a class="result__a" href="https://example.com/s">Search Hit</a>
      <div class="result__snippet">Nice snippet</div>
    </div>
    """
    with patch(
        "crawl4ai_mcp.tools.fetch_page",
        new_callable=AsyncMock,
        return_value=(
            CrawlResult(url="https://duckduckgo.com/", success=True, html=html, title="DDG"),
            {"internal": [], "external": []},
        ),
    ):
        text = await tool_web_search("test", strategies=strategies, engine="duckduckgo", max_results=5)
    data = json.loads(text)
    assert data["engine"] == "duckduckgo"
    assert data["results"][0]["title"] == "Search Hit"
    assert data["results"][0]["url"] == "https://example.com/s"
