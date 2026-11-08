from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_crawl4ai_is_exact_pin():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    crawl = [d for d in deps if d.replace(" ", "").startswith("crawl4ai")]
    assert len(crawl) == 1
    assert crawl[0].replace(" ", "") == "crawl4ai==0.9.5"
