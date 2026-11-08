from pathlib import Path

import yaml

from crawl4ai_mcp.models import SiteStrategy
from crawl4ai_mcp.strategies import detect_strategy, load_strategies


def test_matches_subdomain_not_lookalike():
    s = SiteStrategy(name="知乎", domains=("zhihu.com",), source="builtin")
    assert s.matches("https://zhuanlan.zhihu.com/p/1")
    assert not s.matches("https://notzhihu.com/p/1")


def test_user_overrides_builtin_same_name(tmp_path: Path):
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()
    (builtin / "site.yaml").write_text(
        yaml.dump(
            {
                "name": "Demo",
                "domains": ["example.com"],
                "css_selector": "#builtin",
            }
        ),
        encoding="utf-8",
    )
    (user / "site.yaml").write_text(
        yaml.dump(
            {
                "name": "Demo",
                "domains": ["example.com"],
                "css_selector": "#user",
            }
        ),
        encoding="utf-8",
    )
    strategies = load_strategies(builtin, user)
    matched = detect_strategy(strategies, "https://www.example.com/a")
    assert matched.css_selector == "#user"
    assert matched.source == "user"


def test_invalid_yaml_skipped(tmp_path: Path, caplog):
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()
    (builtin / "ok.yaml").write_text(
        yaml.dump({"name": "Ok", "domains": ["ok.example"]}),
        encoding="utf-8",
    )
    (user / "bad.yaml").write_text(": not: valid: [[\n", encoding="utf-8")
    with caplog.at_level("WARNING"):
        strategies = load_strategies(builtin, user)
    assert any(s.name == "Ok" for s in strategies)
    assert any("bad.yaml" in r.message or "skip" in r.message.lower() for r in caplog.records)


def test_missing_user_dir_loads_builtins_only(tmp_path: Path):
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    (builtin / "ok.yaml").write_text(
        yaml.dump({"name": "Ok", "domains": ["ok.example"]}),
        encoding="utf-8",
    )
    strategies = load_strategies(builtin, tmp_path / "missing-user")
    assert len(strategies) == 1
    assert strategies[0].name == "Ok"


def test_user_domain_overlap_different_name_prefers_user_order(tmp_path: Path):
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()
    (builtin / "a.yaml").write_text(
        yaml.dump(
            {
                "name": "BuiltinSite",
                "domains": ["overlap.example"],
                "css_selector": "#builtin",
            }
        ),
        encoding="utf-8",
    )
    (user / "b.yaml").write_text(
        yaml.dump(
            {
                "name": "UserSite",
                "domains": ["overlap.example"],
                "css_selector": "#user",
            }
        ),
        encoding="utf-8",
    )
    strategies = load_strategies(builtin, user)
    matched = detect_strategy(strategies, "https://overlap.example/x")
    assert matched.name == "UserSite"
    assert matched.source == "user"
