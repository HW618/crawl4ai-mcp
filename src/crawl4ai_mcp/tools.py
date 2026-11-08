from __future__ import annotations

import json

from .converter import convert_to_markdown, extract_summary
from .crawler import crawl_many_pages, crawl_page, deep_crawl_pages, fetch_page
from .deep_crawl import (
    MAX_BATCH_URLS,
    SUPPORTED_DEEP_STRATEGIES,
    clamp_max_depth,
    clamp_max_pages,
)
from .models import CrawlResult, SiteStrategy
from .search import SUPPORTED_ENGINES, build_serp_url, parse_serp_html


def _validate_url(url: str) -> str | None:
    if not url.startswith(("http://", "https://")):
        return f"无效的 URL: {url}。请提供以 http:// 或 https:// 开头的完整 URL。"
    return None


def _cap_links(
    links: dict[str, list[dict[str, str]]], max_links: int
) -> dict[str, list[dict[str, str]]]:
    return {
        "internal": list(links.get("internal") or [])[:max_links],
        "external": list(links.get("external") or [])[:max_links],
    }


async def tool_convert_url(
    url: str,
    *,
    strategies: list[SiteStrategy],
    include_metadata: bool = True,
    include_images: bool = True,
    include_links: bool = True,
    timeout_sec: int = 45,
    max_chars: int | None = None,
    cdp_url: str | None = None,
) -> str:
    if err := _validate_url(url):
        return err
    result = await crawl_page(
        url,
        strategies,
        timeout_ms=timeout_sec * 1000,
        cdp_url=cdp_url,
    )
    convert_kwargs = dict(
        include_metadata=include_metadata,
        include_images=include_images,
        include_links=include_links,
    )
    if max_chars is not None:
        convert_kwargs["max_chars"] = max_chars
    text = convert_to_markdown(result, **convert_kwargs)
    if "strategy:" not in text:
        text = text.rstrip() + f"\n\nstrategy: {result.strategy_name or '普通网页'}\n"
    return text


async def tool_extract_summary(
    url: str,
    *,
    strategies: list[SiteStrategy],
    max_length: int = 3000,
    timeout_sec: int = 45,
    cdp_url: str | None = None,
) -> str:
    if err := _validate_url(url):
        return err
    result = await crawl_page(
        url,
        strategies,
        timeout_ms=timeout_sec * 1000,
        cdp_url=cdp_url,
    )
    return extract_summary(result, max_length=max_length)


def tool_list_site_strategies(strategies: list[SiteStrategy], filter: str | None = None) -> str:
    rows = []
    needle = (filter or "").casefold()
    for strategy in strategies:
        if needle and needle not in strategy.name.casefold() and not any(
            needle in d for d in strategy.domains
        ):
            continue
        rows.append(
            {
                "name": strategy.name,
                "domains": list(strategy.domains),
                "source": strategy.source,
            }
        )
    return json.dumps(rows, ensure_ascii=False, indent=2)


async def tool_fetch_url(
    url: str,
    *,
    strategies: list[SiteStrategy],
    prefetch: bool = False,
    timeout_sec: int = 45,
    max_html_chars: int = 50000,
    max_links: int = 50,
    cdp_url: str | None = None,
) -> str:
    if err := _validate_url(url):
        return json.dumps(
            {
                "success": False,
                "url": url,
                "title": "",
                "prefetch": prefetch,
                "html": "",
                "links": {"internal": [], "external": []},
                "error": err,
            },
            ensure_ascii=False,
        )
    result, links = await fetch_page(
        url,
        strategies,
        prefetch=prefetch,
        timeout_ms=timeout_sec * 1000,
        cdp_url=cdp_url,
    )
    html = result.html or ""
    if max_html_chars >= 0 and len(html) > max_html_chars:
        html = html[:max_html_chars]
    return json.dumps(
        {
            "success": result.success,
            "url": result.url or url,
            "title": result.title or "",
            "prefetch": prefetch,
            "html": html,
            "links": _cap_links(links, max(0, max_links)),
            "error": result.error or "",
        },
        ensure_ascii=False,
    )


def _pages_payload(
    rows: list[dict],
    *,
    error: str = "",
) -> str:
    succeeded = sum(1 for r in rows if r.get("success"))
    failed = len(rows) - succeeded
    return json.dumps(
        {
            "pages": rows,
            "stats": {"crawled": len(rows), "succeeded": succeeded, "failed": failed},
            "error": error,
        },
        ensure_ascii=False,
    )


def _page_row(
    result: CrawlResult,
    *,
    depth: int | None = None,
    score: float | None = None,
    max_chars: int | None = None,
) -> dict:
    markdown = ""
    if result.success:
        convert_kwargs: dict = {}
        if max_chars is not None:
            convert_kwargs["max_chars"] = max_chars
        markdown = convert_to_markdown(result, **convert_kwargs)
    row: dict = {
        "url": result.url,
        "title": result.title or "",
        "markdown": markdown,
        "success": bool(result.success),
        "error": "" if result.success else (result.error or "crawl failed"),
        "strategy_name": result.strategy_name or "",
    }
    if depth is not None:
        row["depth"] = depth
    if score is not None:
        row["score"] = score
    return row


async def tool_crawl_many(
    urls: list[str],
    *,
    strategies: list[SiteStrategy],
    timeout_sec: int = 45,
    max_chars: int | None = None,
    cdp_url: str | None = None,
) -> str:
    items = list(urls or [])
    if not items:
        return _pages_payload([], error="urls is required and must be non-empty")
    if len(items) > MAX_BATCH_URLS:
        return _pages_payload([], error=f"Too many urls: {len(items)} (max {MAX_BATCH_URLS})")
    for item in items:
        if err := _validate_url(item):
            return _pages_payload([], error=err)

    results, hard_error = await crawl_many_pages(
        items,
        strategies,
        timeout_ms=timeout_sec * 1000,
        cdp_url=cdp_url,
    )
    if hard_error and not results:
        return _pages_payload([], error=hard_error)
    rows = [_page_row(result, max_chars=max_chars) for result in results]
    return _pages_payload(rows, error=hard_error)


async def tool_deep_crawl(
    url: str,
    *,
    strategies: list[SiteStrategy],
    strategy: str = "bfs",
    max_depth: int = 2,
    max_pages: int = 50,
    include_external: bool = False,
    keywords: list[str] | None = None,
    timeout_sec: int = 45,
    max_chars: int | None = None,
    cdp_url: str | None = None,
) -> str:
    if err := _validate_url(url):
        return _pages_payload([], error=err)
    strategy_norm = (strategy or "bfs").strip().lower()
    if strategy_norm not in SUPPORTED_DEEP_STRATEGIES:
        return _pages_payload(
            [],
            error=f"Unsupported deep crawl strategy: {strategy}. Choose one of {', '.join(SUPPORTED_DEEP_STRATEGIES)}",
        )
    hits, hard_error = await deep_crawl_pages(
        url,
        strategies,
        strategy=strategy_norm,
        max_depth=clamp_max_depth(max_depth),
        max_pages=clamp_max_pages(max_pages),
        include_external=include_external,
        keywords=keywords,
        timeout_ms=timeout_sec * 1000,
        cdp_url=cdp_url,
    )
    if hard_error and not hits:
        return _pages_payload([], error=hard_error)
    rows = [
        _page_row(result, depth=depth, score=score, max_chars=max_chars)
        for result, depth, score in hits
    ]
    return _pages_payload(rows, error=hard_error)


async def tool_web_search(
    query: str,
    *,
    strategies: list[SiteStrategy],
    engine: str = "duckduckgo",
    max_results: int = 8,
    timeout_sec: int = 45,
    cdp_url: str | None = None,
) -> str:
    engine_norm = (engine or "duckduckgo").strip().lower()
    q = (query or "").strip()
    max_n = max(1, min(int(max_results or 8), 20))
    payload = {"engine": engine_norm, "query": q, "results": [], "error": ""}

    if engine_norm not in SUPPORTED_ENGINES:
        payload["error"] = f"Unsupported search engine: {engine}. Choose one of {', '.join(SUPPORTED_ENGINES)}"
        return json.dumps(payload, ensure_ascii=False)
    if not q:
        payload["error"] = "query is required"
        return json.dumps(payload, ensure_ascii=False)

    serp_url = build_serp_url(engine_norm, q)
    result, _ = await fetch_page(
        serp_url,
        strategies,
        prefetch=True,
        timeout_ms=timeout_sec * 1000,
        cdp_url=cdp_url,
    )
    if not result.success:
        payload["error"] = result.error or "SERP fetch failed"
        return json.dumps(payload, ensure_ascii=False)

    rows = parse_serp_html(engine_norm, result.html, max_results=max_n, base_url=serp_url)
    payload["results"] = rows
    if not rows:
        payload["error"] = "No organic results parsed (SERP may be blocked or layout changed)"
    return json.dumps(payload, ensure_ascii=False)
