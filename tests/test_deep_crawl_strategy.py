from crawl4ai.deep_crawling import (
    BFSDeepCrawlStrategy,
    BestFirstCrawlingStrategy,
    DFSDeepCrawlStrategy,
)

from crawl4ai_mcp.deep_crawl import (
    build_deep_strategy,
    clamp_max_depth,
    clamp_max_pages,
)


def test_clamps():
    assert clamp_max_depth(None) == 2
    assert clamp_max_depth(9) == 5
    assert clamp_max_depth(-1) == 0
    assert clamp_max_pages(None) == 50
    assert clamp_max_pages(0) == 1
    assert clamp_max_pages(200) == 100


def test_build_bfs_dfs_best_first():
    assert isinstance(build_deep_strategy("bfs", max_depth=1, max_pages=3), BFSDeepCrawlStrategy)
    assert isinstance(build_deep_strategy("dfs", max_depth=1, max_pages=3), DFSDeepCrawlStrategy)
    s = build_deep_strategy("best_first", max_depth=1, max_pages=3, keywords=["a"])
    assert isinstance(s, BestFirstCrawlingStrategy)


def test_best_first_without_keywords_ok():
    assert isinstance(
        build_deep_strategy("best_first", max_depth=1, max_pages=3, keywords=[]),
        BestFirstCrawlingStrategy,
    )


def test_include_external_passed():
    s = build_deep_strategy("bfs", max_depth=1, max_pages=2, include_external=True)
    assert s.include_external is True


def test_unknown_strategy_raises():
    import pytest

    with pytest.raises(ValueError):
        build_deep_strategy("random", max_depth=1, max_pages=1)
