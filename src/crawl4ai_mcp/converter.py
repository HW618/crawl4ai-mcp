"""Convert crawl results to Markdown or plain-text summaries."""

from __future__ import annotations

import re
from urllib.parse import urljoin

import yaml
from bs4 import BeautifulSoup

from .models import CrawlResult

MAX_MARKDOWN_LENGTH = 50000
_YAML_NEEDS_QUOTE = re.compile(r'^[\s>|*&!%@`\[\]{},#?-]|:\s|\s#|["\n\r\t]|:\s*$')


def _yaml_type_unsafe(text: str) -> bool:
    try:
        loaded = yaml.safe_load(f"k: {text}")
    except Exception:
        return True
    val = loaded.get("k") if isinstance(loaded, dict) else loaded
    return val is None or isinstance(val, (bool, int, float))


def _yaml_scalar(value: str) -> str:
    text = " ".join(str(value).split())
    if not text:
        return '""'
    if _YAML_NEEDS_QUOTE.search(text) or _yaml_type_unsafe(text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _fix_links(md: str, base_url: str) -> str:
    if not base_url:
        return md

    def repl(match: re.Match, is_image: bool) -> str:
        text, link = match.group(1), match.group(2)
        if link.startswith(("http://", "https://", "data:", "#", "mailto:")):
            return match.group(0)
        prefix = "!" if is_image else ""
        return f"{prefix}[{text}]({urljoin(base_url, link)})"

    md = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", lambda m: repl(m, True), md)
    md = re.sub(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)\)", lambda m: repl(m, False), md)
    return md


def _strip_images(md: str) -> str:
    return re.sub(r"<img[^>]*>", "", re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", md))


def _strip_links(md: str) -> str:
    return re.sub(r"(?<!!)\[([^\]]+)\]\([^)]*\)", r"\1", md)


def _squeeze_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _table_to_pipe(html_table: str) -> str:
    soup = BeautifulSoup(html_table, "html.parser")
    if (
        len(soup.find_all("table")) > 1
        or soup.find(attrs={"rowspan": True})
        or soup.find(attrs={"colspan": True})
        or soup.find(["img", "ul", "ol", "pre", "blockquote"])
    ):
        return html_table
    rows = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        values = [" ".join(c.get_text(" ", strip=True).split()).replace("|", "\\|") for c in cells]
        rows.append(values)
    if not rows:
        return html_table
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    header, body = rows[0], rows[1:]
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join([" --- "] * width) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


_TABLE_OPEN = re.compile(r"<table\b[^>]*>", re.I)
_TABLE_CLOSE = re.compile(r"</table\s*>", re.I)


def _outer_table_spans(md: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    while True:
        opened = _TABLE_OPEN.search(md, cursor)
        if not opened:
            break
        depth = 1
        pos = opened.end()
        end = None
        while depth:
            nxt_open = _TABLE_OPEN.search(md, pos)
            nxt_close = _TABLE_CLOSE.search(md, pos)
            if not nxt_close:
                break
            if nxt_open and nxt_open.start() < nxt_close.start():
                depth += 1
                pos = nxt_open.end()
            else:
                depth -= 1
                pos = nxt_close.end()
                if depth == 0:
                    end = pos
        if end is None:
            cursor = opened.end()
            continue
        spans.append((opened.start(), end))
        cursor = end
    return spans


def _html_tables_to_markdown(md: str) -> str:
    spans = _outer_table_spans(md)
    if not spans:
        return md
    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.append(md[cursor:start])
        raw = md[start:end]
        try:
            table = _table_to_pipe(raw)
        except Exception:
            table = raw
        parts.append("\n\n" + table.strip() + "\n\n")
        cursor = end
    parts.append(md[cursor:])
    return "".join(parts)


def _yaml_header(result: CrawlResult) -> list[str]:
    lines = ["---", f"title: {_yaml_scalar(result.title or '无标题')}"]
    if result.author:
        lines.append(f"author: {_yaml_scalar(result.author)}")
    if result.date:
        lines.append(f"date: {_yaml_scalar(result.date)}")
    lines.append(f"source: {_yaml_scalar(result.url)}")
    if result.strategy_name:
        lines.append(f"strategy: {_yaml_scalar(result.strategy_name)}")
    lines += ["---", ""]
    return lines


def convert_to_markdown(
    result: CrawlResult,
    *,
    include_metadata: bool = True,
    include_images: bool = True,
    include_links: bool = True,
    max_chars: int | None = MAX_MARKDOWN_LENGTH,
) -> str:
    if not result.success:
        return f"❌ 抓取失败: {result.url}\n{result.error}"

    md = _html_tables_to_markdown(result.markdown)
    md = _fix_links(md, result.url)
    if not include_images:
        md = _strip_images(md)
    if not include_links:
        md = _strip_links(md)
    md = _squeeze_blank_lines(md)

    out = _yaml_header(result) if include_metadata else []
    first_heading = re.search(r"^#{1,3}\s+(.+)$", md, re.M)
    if (
        result.title
        and result.title != "无标题"
        and not (first_heading and first_heading.group(1).strip() == result.title.strip())
    ):
        out += [f"# {result.title}", ""]
    out.append(md)

    text = "\n".join(out)
    if max_chars and len(text) > max_chars:
        total = len(text)
        text = (
            text[:max_chars]
            + "\n\n...\n\n"
            + f"[内容已截断，原始内容共 {total} 字符；需要完整内容请增大 max_chars]"
        )
    return text


def extract_summary(result: CrawlResult, *, max_length: int = 3000) -> str:
    if not result.success:
        return f"❌ 抓取失败: {result.url}\n{result.error}"

    text = _strip_links(_strip_images(result.markdown))
    text = re.sub(r"[#*_`>]+", "", text)
    text = _squeeze_blank_lines(text)
    if len(text) > max_length:
        text = text[:max_length] + "..."

    lines = [f"📄 **{result.title or '无标题'}**", f"🔗 来源: {result.url}"]
    if result.author:
        lines.append(f"✍️ 作者: {result.author}")
    if result.strategy_name:
        lines.append(f"strategy: {result.strategy_name}")
    lines += ["", "---", "", text]
    return "\n".join(lines)
