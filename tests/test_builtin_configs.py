from pathlib import Path

from crawl4ai_mcp.strategies import detect_strategy, load_strategies

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = ROOT / "configs"


def test_builtin_weixin_and_zhihu_detection():
    strategies = load_strategies(CONFIGS, None)
    weixin = detect_strategy(strategies, "https://mp.weixin.qq.com/s/x")
    assert weixin.name == "微信公众号"
    assert weixin.js_snippets, "WeChat should resolve lazy_images snippet"
    zhihu = detect_strategy(strategies, "https://zhuanlan.zhihu.com/p/1")
    assert zhihu.name == "知乎"
    assert len(zhihu.js_snippets) >= 2
    wiki = detect_strategy(
        strategies, "https://en.wikipedia.org/wiki/Python_(programming_language)"
    )
    assert wiki.name == "维基百科"
    assert wiki.css_selector and "mw-content-text" in wiki.css_selector
    hn = detect_strategy(strategies, "https://news.ycombinator.com/")
    assert hn.name == "Hacker News"
    assert hn.css_selector == "#bigbox table"
