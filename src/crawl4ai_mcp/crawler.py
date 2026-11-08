"""CDP-only page crawler built on crawl4ai (no local headless fallback)."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from collections.abc import Mapping

from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

from .models import CrawlResult, SiteStrategy
from .strategies import detect_strategy

logger = logging.getLogger(__name__)

_META_DIV_CLASS = "mtp-meta"
MIN_ACCEPT_CHARS = 400
MARKDOWN_OPTIONS = {"bypass_tables": True}


class CdpConfigError(RuntimeError):
    """Raised when CDP_URL is missing or not a compliant CDP endpoint."""


def require_cdp_url(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    url = str(source.get("CDP_URL", "")).strip().rstrip("/")
    if not url:
        raise CdpConfigError("CDP_URL is required and must point at an external CDP browser")
    return url


def is_valid_cdp(cdp_url: str, timeout: float = 1.5) -> bool:
    if not cdp_url.startswith(("http://", "https://")):
        return False
    try:
        with urllib.request.urlopen(f"{cdp_url}/json/version", timeout=timeout) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8", "ignore"))
            return bool(data.get("webSocketDebuggerUrl"))
    except Exception:
        return False


def assert_cdp_ready(cdp_url: str | None = None) -> str:
    url = cdp_url or require_cdp_url()
    if not is_valid_cdp(url):
        raise CdpConfigError(f"CDP endpoint is not available or not compliant: {url}")
    return url


def build_markdown_generator() -> DefaultMarkdownGenerator:
    return DefaultMarkdownGenerator(options=dict(MARKDOWN_OPTIONS))


def build_browser_config(cdp_url: str, verbose: bool = False) -> BrowserConfig:
    return BrowserConfig(
        cdp_url=cdp_url,
        headless=False,
        user_agent_mode="random",
        use_managed_browser=True,
        cdp_cleanup_on_close=False,
        verbose=verbose,
    )


def _short_error(err: object) -> str:
    text = " ".join(str(err).split())
    low = text.lower()
    if "cdp" in low or "connect" in low or "connection" in low:
        return f"CDP browser connection failed: {text[:300]}"
    if "Wait condition failed" in text or "timeout" in low:
        return (
            "页面正文未在超时时间内出现。常见原因：链接已失效、需要登录、或站点触发风控。"
        )
    if len(text) > 300:
        return text[:300] + " ..."
    return text or "crawl failed"


def _clean_title(title: str, strategy: SiteStrategy) -> str:
    t = title.strip()
    for suffix in strategy.title_suffixes:
        idx = t.find(suffix)
        if idx > 0:
            t = t[:idx].strip()
    return t


def _build_meta_inject_js(container_selector: str, strategy: SiteStrategy) -> str:
    return f"""
(() => {{
    const q = s => {{ const el = s ? document.querySelector(s) : null;
                      return el ? el.textContent.trim().slice(0, 200) : ''; }};
    const attr = v => (v || '').replace(/"/g, '&quot;');
    const container = document.querySelector('{container_selector}');
    if (!container || container.querySelector('.{_META_DIV_CLASS}')) return;
    const div = document.createElement('div');
    div.className = '{_META_DIV_CLASS}';
    div.style.display = 'none';
    div.setAttribute('data-title', attr(q('{strategy.title_selector or ""}') || document.title));
    div.setAttribute('data-author', attr(q('{strategy.author_selector or ""}')));
    div.setAttribute('data-date', attr(q('{strategy.date_selector or ""}')));
    container.insertBefore(div, container.firstChild);
}})()
"""


def _extract_injected_meta(html: str) -> dict:
    try:
        div = BeautifulSoup(html, "lxml").find(class_=_META_DIV_CLASS)
        if div:
            return {k: (div.get(f"data-{k}") or "") for k in ("title", "author", "date")}
    except Exception as exc:
        logger.debug("meta parse failed: %s", exc)
    return {}


def _pick_meta(meta: dict, *keys: str) -> str:
    for key in keys:
        value = meta.get(key)
        if value:
            return str(value).strip()
    return ""


def _dedupe_repeats(md: str, min_block: int = 300) -> str:
    text = md.strip()
    if len(text) < min_block * 2:
        return md
    lines = text.split("\n")
    anchor = lines[0].strip()
    if not anchor:
        return md
    for i in range(1, len(lines)):
        if lines[i].strip() != anchor:
            continue
        head = "\n".join(lines[:i]).strip()
        rest = "\n".join(lines[i:]).strip()
        if len(head) < min_block or not rest.startswith(head):
            continue
        remainder = rest[len(head) :].strip()
        while remainder.startswith(head):
            remainder = remainder[len(head) :].strip()
        if not remainder:
            return head
    return md


def _content_selectors(strategy: SiteStrategy) -> list[str | None]:
    if not strategy.css_selector:
        return [None]
    return [strategy.css_selector, *strategy.css_selector_fallbacks]


async def _crawl_once(
    url: str,
    strategy: SiteStrategy,
    cdp_url: str,
    timeout_ms: int,
    verbose: bool,
    css_selector: str | None,
) -> CrawlResult:
    selector = strategy.css_selector if css_selector is None else css_selector
    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        markdown_generator=build_markdown_generator(),
        css_selector=selector,
        excluded_selector=strategy.excluded_selector,
        excluded_tags=["script", "style", "noscript", "iframe", "nav", "footer"],
        wait_for=strategy.wait_for,
        js_code=(
            strategy.js_snippets
            + ([_build_meta_inject_js(selector, strategy)] if selector else [])
        )
        or None,
        page_timeout=timeout_ms,
        word_count_threshold=5,
        verbose=verbose,
        log_console=verbose,
    )
    out = CrawlResult(url=url, strategy_name=strategy.name)
    try:
        async with AsyncWebCrawler(config=build_browser_config(cdp_url, verbose)) as crawler:
            result = await crawler.arun(url=url, config=run_cfg)
    except Exception as exc:
        out.error = _short_error(exc)
        return out

    if not result.success:
        out.error = _short_error(result.error_message or "抓取失败")
        return out

    meta = dict(result.metadata or {})
    out.html = result.html or ""
    raw_md = str(result.markdown.raw_markdown) if result.markdown else ""
    out.markdown = _dedupe_repeats(raw_md)
    injected = _extract_injected_meta(out.html) if selector else {}
    out.title = _clean_title(
        injected.get("title") or _pick_meta(meta, "title", "og:title"),
        strategy,
    )
    out.author = injected.get("author") or _pick_meta(meta, "author", "article:author")
    out.date = injected.get("date") or _pick_meta(
        meta, "article:published_time", "date", "pubdate"
    )
    out.success = bool(out.markdown or out.html)
    if not out.success:
        out.error = f"页面加载成功但未提取到正文（策略：{strategy.name}）"
    return out


async def crawl_page(
    url: str,
    strategies: list[SiteStrategy],
    *,
    timeout_ms: int = 45000,
    verbose: bool = False,
    cdp_url: str | None = None,
) -> CrawlResult:
    """Crawl one URL using only an external CDP browser."""
    strategy = detect_strategy(strategies, url)
    # Explicit cdp_url skips the live probe (tests / pre-validated callers).
    resolved = assert_cdp_ready() if cdp_url is None else cdp_url

    selectors = _content_selectors(strategy)
    best: CrawlResult | None = None
    for sel in selectors:
        result = await _crawl_once(url, strategy, resolved, timeout_ms, verbose, sel)
        if result.success and len(result.markdown) >= MIN_ACCEPT_CHARS:
            return result
        if best is None or len(result.markdown or "") > len(best.markdown or ""):
            best = result
    return best or CrawlResult(url=url, strategy_name=strategy.name, error="crawl failed")
