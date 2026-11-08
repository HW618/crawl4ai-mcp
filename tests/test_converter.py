from crawl4ai_mcp.converter import convert_to_markdown, extract_summary
from crawl4ai_mcp.models import CrawlResult


def _ok(**kwargs) -> CrawlResult:
    base = dict(
        url="https://example.com/post",
        title="Hello",
        author="Ada",
        date="2024-01-01",
        markdown="# Hello\n\n![pic](https://example.com/a.png)\n\nSee [docs](https://example.com/docs) for more.\n\nPlain paragraph.\n",
        html="",
        success=True,
        error="",
        strategy_name="普通网页",
    )
    base.update(kwargs)
    return CrawlResult(**base)


def test_convert_includes_metadata_by_default():
    text = convert_to_markdown(_ok())
    assert text.startswith("---")
    assert "title:" in text
    assert "source:" in text
    assert "Ada" in text or "author:" in text


def test_convert_can_omit_metadata():
    text = convert_to_markdown(_ok(), include_metadata=False)
    assert not text.startswith("---")


def test_convert_strips_images_and_links():
    text = convert_to_markdown(
        _ok(),
        include_metadata=False,
        include_images=False,
        include_links=False,
    )
    assert "![" not in text
    assert "](https://example.com/docs)" not in text
    assert "docs" in text
    assert "pic" in text


def test_extract_summary_respects_max_length():
    long_md = "word " * 500
    text = extract_summary(_ok(markdown=long_md, title="T"), max_length=40)
    assert text.endswith("...")
    body = text.split("---", 1)[-1]
    assert len(body.strip()) <= 43  # max_length + ellipsis
