"""Deep-crawl strategy builders and input clamps."""

from __future__ import annotations

from crawl4ai.deep_crawling import (
    BFSDeepCrawlStrategy,
    BestFirstCrawlingStrategy,
    DFSDeepCrawlStrategy,
)
from crawl4ai.deep_crawling.scorers import KeywordRelevanceScorer

SUPPORTED_DEEP_STRATEGIES = ("bfs", "dfs", "best_first")
MAX_BATCH_URLS = 100


def clamp_max_depth(value: int | None) -> int:
    if value is None:
        return 2
    return max(0, min(int(value), 5))


def clamp_max_pages(value: int | None) -> int:
    if value is None:
        return 50
    return max(1, min(int(value), 100))


def build_deep_strategy(
    strategy: str,
    *,
    max_depth: int,
    max_pages: int,
    include_external: bool = False,
    keywords: list[str] | None = None,
) -> object:
    name = (strategy or "").strip().lower()
    if name not in SUPPORTED_DEEP_STRATEGIES:
        raise ValueError(f"Unsupported deep crawl strategy: {strategy}")
    kw = [k for k in (keywords or []) if str(k).strip()]
    scorer = KeywordRelevanceScorer(keywords=kw) if kw else None
    kwargs = dict(
        max_depth=max_depth,
        max_pages=max_pages,
        include_external=include_external,
        url_scorer=scorer,
    )
    if name == "bfs":
        return BFSDeepCrawlStrategy(**kwargs)
    if name == "dfs":
        return DFSDeepCrawlStrategy(**kwargs)
    return BestFirstCrawlingStrategy(**kwargs)
