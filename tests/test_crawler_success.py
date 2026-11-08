from crawl4ai_mcp.models import CrawlResult
from crawl4ai_mcp.converter import convert_to_markdown


def test_empty_markdown_with_html_is_not_presented_as_success_body():
    # After crawler fix, success=False when markdown empty; converter should surface error.
    result = CrawlResult(
        url="https://example.com/",
        html="<html></html>",
        markdown="   ",
        success=False,
        error="页面加载成功但未提取到正文（策略：普通网页）",
        strategy_name="普通网页",
    )
    text = convert_to_markdown(result)
    assert "抓取失败" in text or "未提取" in text
    assert not text.startswith("---")
