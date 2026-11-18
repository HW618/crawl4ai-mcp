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


def test_simple_html_table_becomes_a_pipe_table():
    text = convert_to_markdown(
        _ok(
            markdown="Intro paragraph.<table><tr><th>A</th><th>B</th></tr><tr><td colspan=\"2\">wide</td></tr><tr><td>1</td><td>2</td></tr></table>Outro paragraph.",
            title="Hello",
        ),
        include_metadata=False,
    )
    assert "<table" not in text.lower()
    table = "| A | B |\n| --- | --- |\n| wide |  |\n| 1 | 2 |"
    assert f"Intro paragraph.\n\n{table}\n\nOutro paragraph." in text


def test_nested_layout_table_keeps_story_link_without_html():
    html = """
    <table id="hnmain"><tr><td>
      <table class="itemlist">
        <tr class="athing">
          <td class="title"><span class="rank">1.</span></td>
          <td></td>
          <td class="title"><a href="https://example.com/post">Example story</a></td>
        </tr>
        <tr><td colspan="2"></td><td class="subtext">10 points by ada | 3 comments</td></tr>
      </table>
    </td></tr></table>
    """
    text = convert_to_markdown(_ok(markdown=html, title="Hacker News"), include_metadata=False)
    assert "<table" not in text.lower()
    assert "| 1. |  | [Example story](https://example.com/post) |" in text
    assert "| --- | --- | --- |" in text
    assert "|  |  | 10 points by ada \\| 3 comments |" in text


def test_layout_row_tags_do_not_survive_table_conversion():
    html = (
        '<tr id="bigbox"><td><table><tr><td>1.</td>'
        '<td><a href="https://example.com/post">Story</a></td></tr></table></td></tr>'
    )
    text = convert_to_markdown(_ok(markdown=html, title="Hacker News"), include_metadata=False)
    assert "<tr" not in text.lower()
    assert "<td" not in text.lower()
    assert "Story" in text


def test_extract_summary_respects_max_length():
    long_md = "word " * 500
    text = extract_summary(_ok(markdown=long_md, title="T"), max_length=40)
    assert text.endswith("...")
    body = text.split("---", 1)[-1]
    assert len(body.strip()) <= 43  # max_length + ellipsis
