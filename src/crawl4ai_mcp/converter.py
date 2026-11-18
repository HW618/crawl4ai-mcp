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


def _inline_markdown(node) -> None:
    for anchor in list(node.find_all("a")):
        href = (anchor.get("href") or "").strip()
        label = " ".join(anchor.get_text(" ", strip=True).split())
        if href and label:
            anchor.replace_with(f"[{label}]({href})")
        elif label:
            anchor.replace_with(label)
        else:
            anchor.decompose()
    for image in list(node.find_all("img")):
        src = (image.get("src") or "").strip()
        alt = " ".join((image.get("alt") or "").split())
        if src:
            image.replace_with(f"![{alt}]({src})")
        else:
            image.decompose()


def _cell_text(cell) -> str:
    _inline_markdown(cell)
    return cell.get_text("\n", strip=True)


def _span(cell, name: str) -> int:
    try:
        return max(1, int(cell.get(name) or 1))
    except ValueError:
        return 1


def _table_grid(table) -> list[list[str]]:
    """Keep each HTML row's columns, including cells left empty by colspan or rowspan."""
    pending: dict[int, int] = {}
    grid: list[list[str]] = []
    for tr in table.find_all("tr"):
        if tr.find_parent("tr") is not None:
            continue
        cells = tr.find_all(["th", "td"], recursive=False)
        if not cells and not any(pending.values()):
            continue
        parsed = [(_cell_text(cell), _span(cell, "colspan"), _span(cell, "rowspan")) for cell in cells]
        row: list[str] = []
        col = 0
        cell_i = 0
        while cell_i < len(parsed) or any(count > 0 for count in pending.values()):
            if pending.get(col, 0) > 0:
                row.append("")
                pending[col] -= 1
                col += 1
                continue
            if cell_i >= len(parsed):
                break
            text, colspan, rowspan = parsed[cell_i]
            cell_i += 1
            for offset in range(colspan):
                row.append(text if offset == 0 else "")
                if rowspan > 1:
                    pending[col] = rowspan - 1
                col += 1
        if row:
            grid.append(row)
    if not grid:
        return []
    width = max(len(row) for row in grid)
    return [row + [""] * (width - len(row)) for row in grid]


def _pipe_row(values: list[str]) -> str:
    cells = [" ".join(value.split()).replace("|", "\\|") for value in values]
    return "| " + " | ".join(cells) + " |"


def _contains_pipe_table(text: str) -> bool:
    return any(line.strip().startswith("|") and line.strip().endswith("|") for line in text.splitlines())


def _render_table(html_table: str) -> str:
    soup = BeautifulSoup(html_table, "html.parser")
    table = soup.find("table")
    if table is None:
        return BeautifulSoup(html_table, "html.parser").get_text("\n", strip=True)
    rows = _table_grid(table)
    if not rows:
        return ""
    if any(_contains_pipe_table(cell) for row in rows for cell in row):
        blocks = [cell.strip() for row in rows for cell in row if cell.strip()]
        return "\n\n".join(blocks)
    lines = [_pipe_row(rows[0]), "|" + "|".join([" --- "] * len(rows[0])) + "|"]
    lines += [_pipe_row(row) for row in rows[1:]]
    return "\n".join(lines)


_TABLE_OPEN = re.compile(r"<table\b[^>]*>", re.I)
_TABLE_CLOSE = re.compile(r"</table\s*>", re.I)
_LAYOUT_TAG = re.compile(r"</?(?:tr|td|th|tbody|thead|tfoot)\b[^>]*>", re.I)


def _table_end(md: str, start: int) -> int | None:
    opened = _TABLE_OPEN.match(md, start)
    if not opened:
        return None
    depth = 1
    pos = opened.end()
    while depth:
        nxt_open = _TABLE_OPEN.search(md, pos)
        nxt_close = _TABLE_CLOSE.search(md, pos)
        if not nxt_close:
            return None
        if nxt_open and nxt_open.start() < nxt_close.start():
            depth += 1
            pos = nxt_open.end()
        else:
            depth -= 1
            pos = nxt_close.end()
    return pos


def _innermost_table_spans(md: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    lowered = md.lower()
    while True:
        start = lowered.find("<table", cursor)
        if start < 0:
            break
        end = _table_end(md, start)
        if end is None:
            cursor = start + 6
            continue
        if "<table" not in lowered[start + 6 : end]:
            spans.append((start, end))
            cursor = end
        else:
            cursor = start + 6
    return spans


def _is_pipe_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _separate_pipe_tables(md: str) -> str:
    """Keep each pipe table intact and leave one blank line around it."""
    lines = md.split("\n")
    output: list[str] = []
    index = 0
    while index < len(lines):
        if not _is_pipe_row(lines[index]):
            output.append(lines[index])
            index += 1
            continue
        if output and output[-1].strip():
            output.append("")
        while index < len(lines) and _is_pipe_row(lines[index]):
            output.append(lines[index].strip())
            index += 1
        if index < len(lines) and lines[index].strip():
            output.append("")
    return "\n".join(output)


def _html_tables_to_markdown(md: str) -> str:
    for _ in range(50):
        spans = _innermost_table_spans(md)
        if not spans:
            return _separate_pipe_tables(_LAYOUT_TAG.sub("", md))
        updated = md
        for start, end in reversed(spans):
            raw = updated[start:end]
            try:
                rendered = _render_table(raw)
            except Exception:
                rendered = BeautifulSoup(raw, "html.parser").get_text("\n", strip=True)
            updated = updated[:start] + "\n\n" + rendered.strip() + "\n\n" + updated[end:]
        if updated == md:
            return _separate_pipe_tables(_LAYOUT_TAG.sub("", md))
        md = updated
    return _separate_pipe_tables(_LAYOUT_TAG.sub("", md))


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
