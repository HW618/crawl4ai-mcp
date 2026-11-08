from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class SiteStrategy:
    """Declarative per-site crawl/convert strategy."""

    name: str
    domains: tuple[str, ...] = ()
    css_selector: str | None = None
    css_selector_fallbacks: tuple[str, ...] = ()
    excluded_selector: str | None = None
    wait_for: str | None = None
    js_snippets: list[str] = field(default_factory=list)
    title_suffixes: tuple[str, ...] = ()
    title_selector: str | None = None
    author_selector: str | None = None
    date_selector: str | None = None
    source: str = "builtin"

    def matches(self, url: str) -> bool:
        host = urlparse(url).netloc.lower().split(":")[0]
        return any(host == d or host.endswith("." + d) for d in self.domains)


@dataclass
class CrawlResult:
    url: str = ""
    title: str = ""
    author: str = ""
    date: str = ""
    markdown: str = ""
    html: str = ""
    success: bool = False
    error: str = ""
    strategy_name: str = ""
