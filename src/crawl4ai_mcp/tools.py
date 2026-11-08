from __future__ import annotations

import json

from .converter import convert_to_markdown, extract_summary
from .crawler import crawl_page
from .models import SiteStrategy


def _validate_url(url: str) -> str | None:
    if not url.startswith(("http://", "https://")):
        return f"无效的 URL: {url}。请提供以 http:// 或 https:// 开头的完整 URL。"
    return None


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
