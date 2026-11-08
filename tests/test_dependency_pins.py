import re
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def _crawl4ai_req() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    crawl = [d for d in deps if d.replace(" ", "").startswith("crawl4ai")]
    assert len(crawl) == 1
    return crawl[0].replace(" ", "")


def test_crawl4ai_is_exact_pin():
    req = _crawl4ai_req()
    assert re.fullmatch(r"crawl4ai==\d+\.\d+\.\d+", req), req
    assert ">=" not in req and "<=" not in req and "~=" not in req


def test_operations_docs_cite_pinned_crawl4ai():
    req = _crawl4ai_req()
    version = req.split("==", 1)[1]
    ops = (ROOT / "docs" / "operations.md").read_text(encoding="utf-8")
    assert f"=={version}" in ops or f"`=={version}`" in ops
