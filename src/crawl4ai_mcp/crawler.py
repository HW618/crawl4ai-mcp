"""CDP-only page crawler built on crawl4ai (no local headless fallback)."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import contextvars
import json
import logging
import os
import socket
import ssl
import threading
import urllib.request
from collections.abc import Callable, Mapping
from urllib.parse import urlparse, urlunparse

from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

from .cache import TtlCache
from .deep_crawl import build_deep_strategy, clamp_max_depth, clamp_max_pages
from .models import CrawlResult, SiteStrategy
from .strategies import detect_strategy

logger = logging.getLogger(__name__)

_META_DIV_CLASS = "mtp-meta"
MIN_ACCEPT_CHARS = 400
MARKDOWN_OPTIONS = {"bypass_tables": True}
_BROWSER_ERROR_KEYWORDS = (
    "cdp",
    "connect",
    "connection",
    "target closed",
    "targetclosed",
    "browser",
    "playwright",
    "executable doesn't exist",
    "browsertype",
)


class CdpConfigError(RuntimeError):
    """Raised when CDP_URL is missing or not a compliant CDP endpoint."""


class CrawlerPool:
    """Reuse one started AsyncWebCrawler per CDP endpoint."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._crawler: AsyncWebCrawler | None = None
        self._cdp_url: str | None = None
        self._verbose = False

    async def get(self, cdp_url: str, verbose: bool = False) -> AsyncWebCrawler:
        async with self._lock:
            if self._crawler is not None and self._cdp_url == cdp_url and self._verbose == verbose:
                return self._crawler
            await self._close_unlocked()
            crawler = AsyncWebCrawler(config=build_browser_config(cdp_url, verbose))
            await crawler.start()
            self._crawler = crawler
            self._cdp_url = cdp_url
            self._verbose = verbose
            logger.info("Started shared CDP crawler for %s", cdp_url)
            return crawler

    async def invalidate(self) -> None:
        async with self._lock:
            await self._close_unlocked()

    async def close(self) -> None:
        async with self._lock:
            await self._close_unlocked()

    async def _close_unlocked(self) -> None:
        if self._crawler is None:
            return
        try:
            await self._crawler.close()
        except Exception as exc:
            logger.debug("Error closing shared crawler: %s", exc)
        self._crawler = None
        self._cdp_url = None


_pool = CrawlerPool()
_cache: TtlCache[CrawlResult] = TtlCache(ttl_sec=60.0)
_crawl_hold = contextvars.ContextVar("crawl_hold", default=0)
_crawl_semaphore: asyncio.Semaphore | None = None
_crawl_semaphore_size: int | None = None


def _cache_ttl_from_env() -> float:
    raw = os.environ.get("CRAWL_CACHE_TTL_SEC", "60").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 60.0


def _refresh_cache_from_env() -> None:
    global _cache
    _cache = TtlCache(ttl_sec=_cache_ttl_from_env())


def _max_concurrency() -> int:
    raw = os.environ.get("CRAWL_MAX_CONCURRENCY", "1").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def _reset_crawl_limiter() -> None:
    global _crawl_semaphore, _crawl_semaphore_size
    _crawl_semaphore = None
    _crawl_semaphore_size = None


def _crawl_semaphore_for_now() -> asyncio.Semaphore:
    global _crawl_semaphore, _crawl_semaphore_size
    size = _max_concurrency()
    if _crawl_semaphore is None or _crawl_semaphore_size != size:
        _crawl_semaphore = asyncio.Semaphore(size)
        _crawl_semaphore_size = size
    return _crawl_semaphore


@contextlib.asynccontextmanager
async def crawl_slot():
    """Limit overlapping CDP work. Nested calls on the same task reuse the slot."""
    if _crawl_hold.get() > 0:
        token = _crawl_hold.set(_crawl_hold.get() + 1)
        try:
            yield
        finally:
            _crawl_hold.reset(token)
        return
    semaphore = _crawl_semaphore_for_now()
    await semaphore.acquire()
    token = _crawl_hold.set(1)
    try:
        yield
    finally:
        _crawl_hold.reset(token)
        semaphore.release()


async def reset_crawler_runtime() -> None:
    """Test helper: drop shared crawler + cache."""
    await _pool.close()
    _refresh_cache_from_env()
    _reset_crawl_limiter()


def normalize_cdp_url(url: str) -> str:
    """Accept HTTP discovery URLs and WebSocket debugger URLs.

    A bare ``ws://host:port`` (or ``wss``) has no debugger path. Playwright
    discovers that browser through HTTP ``/json/version``, so those become
    ``http(s)://host:port``. A full ``ws(s)://host/devtools/...`` URL is kept.
    """
    raw = url.strip()
    parsed = urlparse(raw)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https", "ws", "wss"} or not parsed.hostname:
        return raw.rstrip("/")
    if scheme in {"ws", "wss"} and parsed.path in {"", "/"}:
        http_scheme = "https" if scheme == "wss" else "http"
        return urlunparse((http_scheme, parsed.netloc, "", "", "", "")).rstrip("/")
    if parsed.path in {"", "/"}:
        return urlunparse((scheme, parsed.netloc, "", "", "", "")).rstrip("/")
    return raw


def require_cdp_url(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    raw = str(source.get("CDP_URL", "")).strip()
    if not raw:
        raise CdpConfigError("CDP_URL is required and must point at an external CDP browser")
    url = normalize_cdp_url(raw)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https", "ws", "wss"} or not parsed.hostname:
        raise CdpConfigError(f"CDP_URL must be an http(s) or ws(s) endpoint: {raw}")
    return url


def _http_cdp_ok(cdp_url: str, timeout: float) -> bool:
    try:
        with urllib.request.urlopen(f"{cdp_url}/json/version", timeout=timeout) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8", "ignore"))
            return bool(data.get("webSocketDebuggerUrl"))
    except Exception:
        return False


def _ws_cdp_ok(cdp_url: str, timeout: float) -> bool:
    """True when the URL accepts a WebSocket upgrade (CDP debugger socket)."""
    parsed = urlparse(cdp_url)
    host = parsed.hostname
    if not host:
        return False
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    ).encode("ascii")
    raw: socket.socket | None = None
    sock: socket.socket | None = None
    try:
        raw = socket.create_connection((host, port), timeout=timeout)
        sock = raw
        if parsed.scheme == "wss":
            sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        sock.settimeout(timeout)
        sock.sendall(request)
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 8192:
            chunk = sock.recv(1024)
            if not chunk:
                break
            data += chunk
    except Exception:
        return False
    finally:
        for item in (sock, raw):
            if item is None:
                continue
            try:
                item.close()
            except Exception:
                pass
    status = data.split(b"\r\n", 1)[0]
    return b" 101 " in status


def is_valid_cdp(cdp_url: str, timeout: float = 1.5) -> bool:
    url = normalize_cdp_url(cdp_url)
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"}:
        return _http_cdp_ok(url, timeout)
    if parsed.scheme in {"ws", "wss"}:
        return _ws_cdp_ok(url, timeout)
    return False


def assert_cdp_ready(cdp_url: str | None = None) -> str:
    url = normalize_cdp_url(cdp_url) if cdp_url else require_cdp_url()
    if cdp_url:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https", "ws", "wss"} or not parsed.hostname:
            raise CdpConfigError(f"CDP_URL must be an http(s) or ws(s) endpoint: {cdp_url}")
    if not is_valid_cdp(url):
        raise CdpConfigError(f"CDP endpoint is not available or not compliant: {url}")
    return url


def watch_cdp(
    url: str,
    *,
    interval: float,
    stop: threading.Event | None = None,
    sleep: Callable[[float], bool] | None = None,
    check: Callable[[str], bool] = is_valid_cdp,
    die: Callable[[int], None] = os._exit,
) -> None:
    """Poll the CDP endpoint and stop the process when it becomes unhealthy."""
    event = stop or threading.Event()
    waiter = sleep or event.wait
    while True:
        if waiter(interval):
            return
        try:
            healthy = check(url)
        except Exception:
            logger.exception("CDP health check failed for %s", url)
            healthy = False
        if healthy:
            continue
        logger.error("CDP endpoint is unavailable, exiting: %s", url)
        die(1)
        return


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


def _is_browser_error(err: object) -> bool:
    text = str(err).lower()
    return any(k in text for k in _BROWSER_ERROR_KEYWORDS)


def _short_error(err: object) -> str:
    text = " ".join(str(err).split())
    low = text.lower()
    if _is_browser_error(err):
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


def _page_js(strategy: SiteStrategy, selector: str | None) -> list[str] | None:
    """Site snippets plus the meta-inject script used when a content selector is set."""
    snippets = list(strategy.js_snippets)
    if selector:
        snippets.append(_build_meta_inject_js(selector, strategy))
    return snippets or None


def _fragment_html(html: str, selector: str, excluded_selector: str | None) -> str:
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return ""
    nodes = soup.select(selector)
    if not nodes:
        return ""
    if excluded_selector:
        for node in nodes:
            for bad in node.select(excluded_selector):
                bad.decompose()
    return "".join(str(node) for node in nodes)


def _markdown_from_html(html: str, base_url: str) -> str:
    if not html.strip():
        return ""
    generated = build_markdown_generator().generate_markdown(
        html,
        base_url=base_url,
        citations=False,
    )
    raw = getattr(generated, "raw_markdown", None)
    text = str(raw if raw is not None else generated)
    return _dedupe_repeats(text)


def _result_from_probe(
    base: CrawlResult,
    strategy: SiteStrategy,
    markdown: str,
    fragment: str,
) -> CrawlResult:
    injected = _extract_injected_meta(base.html or "")
    out = CrawlResult(
        url=base.url,
        html=fragment or base.html,
        markdown=markdown,
        strategy_name=strategy.name or base.strategy_name,
        title=_clean_title(injected.get("title") or base.title, strategy),
        author=injected.get("author") or base.author,
        date=injected.get("date") or base.date,
    )
    out.success = bool((out.markdown or "").strip())
    if not out.success:
        out.error = f"页面加载成功但未提取到正文（策略：{strategy.name}）"
        out.error_kind = "page"
    return out


def _choose_selector_markdown(
    base: CrawlResult,
    strategy: SiteStrategy,
    selectors: list[str],
) -> CrawlResult:
    """Pick a content selector from HTML already fetched. Does not navigate again."""
    best: CrawlResult | None = None
    for selector in selectors:
        fragment = _fragment_html(base.html, selector, strategy.excluded_selector)
        if not fragment:
            continue
        candidate = _result_from_probe(
            base,
            strategy,
            _markdown_from_html(fragment, base.url),
            fragment,
        )
        if candidate.success and len(candidate.markdown) >= MIN_ACCEPT_CHARS:
            return candidate
        if best is None or len(candidate.markdown or "") > len(best.markdown or ""):
            best = candidate
    return best or base


def _needs_content_retry(result: CrawlResult) -> bool:
    """True when a deep-crawl hit loaded but extracted no markdown."""
    if result.error_kind == "browser" or not result.url:
        return False
    return not (result.markdown or "").strip()


def _cache_key(url: str, strategy_name: str) -> str:
    return f"{strategy_name}\n{url}"


async def _crawl_once(
    url: str,
    strategy: SiteStrategy,
    cdp_url: str,
    timeout_ms: int,
    verbose: bool,
    css_selector: str | None,
) -> CrawlResult:
    # None means capture the full page. Meta-inject still targets the strategy selector.
    selector = css_selector
    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        markdown_generator=build_markdown_generator(),
        css_selector=selector,
        excluded_selector=strategy.excluded_selector,
        excluded_tags=["script", "style", "noscript", "iframe", "nav", "footer"],
        wait_for=strategy.wait_for,
        js_code=_page_js(strategy, selector or strategy.css_selector),
        page_timeout=timeout_ms,
        word_count_threshold=5,
        verbose=verbose,
        log_console=verbose,
    )
    out = CrawlResult(url=url, strategy_name=strategy.name)
    try:
        crawler = await _pool.get(cdp_url, verbose)
        result = await crawler.arun(url=url, config=run_cfg)
    except Exception as exc:
        out.error = _short_error(exc)
        out.error_kind = "browser" if _is_browser_error(exc) else "page"
        if out.error_kind == "browser":
            await _pool.invalidate()
        return out

    if not result.success:
        message = result.error_message or "抓取失败"
        out.error = _short_error(message)
        out.error_kind = "browser" if _is_browser_error(message) else "page"
        if out.error_kind == "browser":
            await _pool.invalidate()
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
    out.success = bool((out.markdown or "").strip())
    if not out.success:
        out.error = f"页面加载成功但未提取到正文（策略：{strategy.name}）"
        out.error_kind = "page"
    return out


def _normalize_links(raw: object) -> dict[str, list[dict[str, str]]]:
    """Normalize crawl4ai links dict to {internal, external}[{href, text}]."""
    out: dict[str, list[dict[str, str]]] = {"internal": [], "external": []}
    if not isinstance(raw, Mapping):
        return out
    for kind in ("internal", "external"):
        items = raw.get(kind) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                continue
            href = str(item.get("href") or item.get("url") or "").strip()
            text = str(item.get("text") or item.get("title") or "").strip()
            if href:
                out[kind].append({"href": href, "text": text})
    return out


def _meta_depth_score(meta: Mapping | None) -> tuple[int | None, float | None]:
    if not isinstance(meta, Mapping):
        return None, None
    depth_raw = meta.get("depth")
    score_raw = meta.get("score")
    depth: int | None
    score: float | None
    try:
        depth = int(depth_raw) if depth_raw is not None else None
    except (TypeError, ValueError):
        depth = None
    try:
        score = float(score_raw) if score_raw is not None else None
    except (TypeError, ValueError):
        score = None
    return depth, score


def _map_crawl4ai_result(raw: object, strategy: SiteStrategy) -> CrawlResult:
    url = str(getattr(raw, "url", "") or "")
    out = CrawlResult(url=url, strategy_name=strategy.name)
    success = bool(getattr(raw, "success", False))
    if not success:
        message = getattr(raw, "error_message", None) or "抓取失败"
        out.error = _short_error(message)
        out.error_kind = "browser" if _is_browser_error(message) else "page"
        return out
    meta = dict(getattr(raw, "metadata", None) or {})
    out.html = getattr(raw, "html", None) or ""
    markdown_obj = getattr(raw, "markdown", None)
    if markdown_obj is not None:
        raw_md = getattr(markdown_obj, "raw_markdown", None)
        out.markdown = _dedupe_repeats(str(raw_md if raw_md is not None else markdown_obj))
    injected = _extract_injected_meta(out.html) if out.html else {}
    out.title = _clean_title(
        injected.get("title") or _pick_meta(meta, "title", "og:title") or "",
        strategy,
    )
    out.author = injected.get("author") or _pick_meta(meta, "author", "article:author")
    out.date = injected.get("date") or _pick_meta(
        meta, "article:published_time", "date", "pubdate"
    )
    out.success = bool((out.markdown or "").strip())
    if not out.success:
        out.error = f"页面加载成功但未提取到正文（策略：{strategy.name}）"
        out.error_kind = "page"
    return out


def build_deep_run_config(
    seed_strategy: SiteStrategy,
    *,
    deep_strategy: object,
    timeout_ms: int,
    verbose: bool = False,
) -> CrawlerRunConfig:
    """Build CrawlerRunConfig for deep crawl using the seed URL's site strategy.

    One crawl4ai config can carry only the primary selector. Pages that come
    back without markdown are re-crawled per URL so fallbacks still run.
    """
    selector = seed_strategy.css_selector
    return CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        markdown_generator=build_markdown_generator(),
        css_selector=selector,
        excluded_selector=seed_strategy.excluded_selector,
        excluded_tags=["script", "style", "noscript", "iframe", "nav", "footer"],
        wait_for=seed_strategy.wait_for,
        js_code=_page_js(seed_strategy, selector),
        page_timeout=timeout_ms,
        word_count_threshold=5,
        verbose=verbose,
        log_console=verbose,
        deep_crawl_strategy=deep_strategy,
    )


async def _normalize_arun_results(raw: object) -> list:
    if raw is None:
        return []
    if hasattr(raw, "__aiter__"):
        return [item async for item in raw]  # type: ignore[misc]
    if isinstance(raw, list):
        return raw
    return [raw]


async def deep_crawl_pages(
    url: str,
    strategies: list[SiteStrategy],
    *,
    strategy: str = "bfs",
    max_depth: int = 2,
    max_pages: int = 50,
    include_external: bool = False,
    keywords: list[str] | None = None,
    timeout_ms: int = 45000,
    verbose: bool = False,
    cdp_url: str | None = None,
) -> tuple[list[tuple[CrawlResult, int | None, float | None]], str]:
    """Deep-crawl from one seed URL. Returns (hits, hard_error)."""
    depth = clamp_max_depth(max_depth)
    pages = clamp_max_pages(max_pages)
    try:
        deep_strategy = build_deep_strategy(
            strategy,
            max_depth=depth,
            max_pages=pages,
            include_external=include_external,
            keywords=keywords,
        )
    except ValueError as exc:
        return [], str(exc)

    resolved = assert_cdp_ready() if cdp_url is None else cdp_url
    seed_strategy = detect_strategy(strategies, url)
    run_cfg = build_deep_run_config(
        seed_strategy,
        deep_strategy=deep_strategy,
        timeout_ms=timeout_ms,
        verbose=verbose,
    )
    async with crawl_slot():
        return await _deep_crawl_loaded(
            url,
            strategies,
            resolved=resolved,
            run_cfg=run_cfg,
            timeout_ms=timeout_ms,
            verbose=verbose,
        )


async def _deep_crawl_loaded(
    url: str,
    strategies: list[SiteStrategy],
    *,
    resolved: str,
    run_cfg: CrawlerRunConfig,
    timeout_ms: int,
    verbose: bool,
) -> tuple[list[tuple[CrawlResult, int | None, float | None]], str]:
    try:
        crawler = await _pool.get(resolved, verbose)
        raw = await crawler.arun(url=url, config=run_cfg)
        items = await _normalize_arun_results(raw)
    except Exception as exc:
        if _is_browser_error(exc):
            await _pool.invalidate()
        return [], _short_error(exc)

    hits: list[tuple[CrawlResult, int | None, float | None]] = []
    saw_browser = False
    for item in items:
        item_url = str(getattr(item, "url", "") or url)
        site = detect_strategy(strategies, item_url)
        mapped = _map_crawl4ai_result(item, site)
        if mapped.error_kind == "browser":
            saw_browser = True
        d, s = _meta_depth_score(getattr(item, "metadata", None))
        hits.append((mapped, d, s))
    if saw_browser:
        await _pool.invalidate()
    elif hits:
        for index, (mapped, depth, score) in enumerate(hits):
            if not _needs_content_retry(mapped):
                continue
            recrawled = await crawl_page(
                mapped.url,
                strategies,
                timeout_ms=timeout_ms,
                verbose=verbose,
                cdp_url=resolved,
            )
            hits[index] = (recrawled, depth, score)
            if recrawled.error_kind == "browser":
                await _pool.invalidate()
                break
    if not hits:
        return [], "Deep crawl returned no pages"
    return hits, ""


async def fetch_page(
    url: str,
    strategies: list[SiteStrategy],
    *,
    prefetch: bool = False,
    timeout_ms: int = 45000,
    verbose: bool = False,
    cdp_url: str | None = None,
) -> tuple[CrawlResult, dict[str, list[dict[str, str]]]]:
    """Fetch HTML (+ optional links) via CDP without requiring markdown success."""
    strategy = detect_strategy(strategies, url)
    resolved = assert_cdp_ready() if cdp_url is None else cdp_url
    empty_links: dict[str, list[dict[str, str]]] = {"internal": [], "external": []}
    out = CrawlResult(url=url, strategy_name=strategy.name)

    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        markdown_generator=None if prefetch else build_markdown_generator(),
        css_selector=None if prefetch else strategy.css_selector,
        excluded_selector=None if prefetch else strategy.excluded_selector,
        excluded_tags=["script", "style", "noscript", "iframe"],
        wait_for=None if prefetch else strategy.wait_for,
        js_code=None if prefetch else (strategy.js_snippets or None),
        page_timeout=timeout_ms,
        word_count_threshold=1,
        verbose=verbose,
        log_console=verbose,
        prefetch=prefetch,
        exclude_external_links=False,
        exclude_internal_links=False,
    )
    try:
        async with crawl_slot():
            crawler = await _pool.get(cdp_url=resolved, verbose=verbose)
            result = await crawler.arun(url=url, config=run_cfg)
    except Exception as exc:
        out.error = _short_error(exc)
        out.error_kind = "browser" if _is_browser_error(exc) else "page"
        if out.error_kind == "browser":
            await _pool.invalidate()
        return out, empty_links

    if not result.success:
        message = result.error_message or "抓取失败"
        out.error = _short_error(message)
        out.error_kind = "browser" if _is_browser_error(message) else "page"
        if out.error_kind == "browser":
            await _pool.invalidate()
        return out, empty_links

    meta = dict(result.metadata or {})
    out.html = result.html or ""
    if result.markdown:
        out.markdown = _dedupe_repeats(str(result.markdown.raw_markdown))
    out.title = _clean_title(_pick_meta(meta, "title", "og:title") or "", strategy)
    out.author = _pick_meta(meta, "author", "article:author")
    out.date = _pick_meta(meta, "article:published_time", "date", "pubdate")
    out.success = bool(out.html.strip())
    if not out.success:
        out.error = f"页面加载成功但未获取到 HTML（策略：{strategy.name}）"
        out.error_kind = "page"
        return out, empty_links
    return out, _normalize_links(result.links)


async def crawl_many_pages(
    urls: list[str],
    strategies: list[SiteStrategy],
    *,
    timeout_ms: int = 45000,
    verbose: bool = False,
    cdp_url: str | None = None,
) -> tuple[list[CrawlResult], str]:
    """Crawl an explicit URL list without deep-link discovery (order preserved)."""
    results: list[CrawlResult] = []
    async with crawl_slot():
        for index, item in enumerate(urls):
            result = await crawl_page(
                item,
                strategies,
                timeout_ms=timeout_ms,
                verbose=verbose,
                cdp_url=cdp_url,
            )
            results.append(result)
            if result.error_kind == "browser":
                await _pool.invalidate()
                skip_msg = result.error or "CDP browser connection failed"
                for skipped in urls[index + 1 :]:
                    results.append(
                        CrawlResult(
                            url=skipped,
                            success=False,
                            error=f"skipped after CDP failure: {skip_msg}",
                            error_kind="browser",
                        )
                    )
                return results, ""
    return results, ""


async def crawl_page(
    url: str,
    strategies: list[SiteStrategy],
    *,
    timeout_ms: int = 45000,
    verbose: bool = False,
    cdp_url: str | None = None,
    use_cache: bool = True,
) -> CrawlResult:
    """Crawl one URL using only an external CDP browser."""
    strategy = detect_strategy(strategies, url)
    resolved = assert_cdp_ready() if cdp_url is None else cdp_url

    # Keep cache TTL in sync with env (tests may change CRAWL_CACHE_TTL_SEC).
    if _cache.ttl_sec != _cache_ttl_from_env():
        _refresh_cache_from_env()

    key = _cache_key(url, strategy.name)
    if use_cache:
        cached = _cache.get(key)
        if cached is not None:
            logger.debug("crawl cache hit for %s", url)
            return cached

    async with crawl_slot():
        selectors = [sel for sel in _content_selectors(strategy) if sel]
        result = await _crawl_once(url, strategy, resolved, timeout_ms, verbose, None)
        if result.error_kind == "browser":
            return result
        if selectors and result.html:
            result = _choose_selector_markdown(result, strategy, selectors)
        elif selectors:
            best = result
            for sel in selectors:
                probed = await _crawl_once(url, strategy, resolved, timeout_ms, verbose, sel)
                if probed.error_kind == "browser":
                    return probed
                if probed.success and len(probed.markdown) >= MIN_ACCEPT_CHARS:
                    result = probed
                    break
                if best is None or len(probed.markdown or "") > len(best.markdown or ""):
                    best = probed
            else:
                result = best or result
        if use_cache and result.success:
            _cache.set(key, result)
        return result
