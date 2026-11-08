import json
from pathlib import Path

from crawl4ai_mcp.cli import main
from crawl4ai_mcp.credentials import write_connection_json


def test_info_prints_connection(tmp_path: Path, capsys, monkeypatch):
    write_connection_json(tmp_path, host="127.0.0.1", port=9000, path="/mcp", api_key="k")
    monkeypatch.setenv("CRAWL4AI_MCP_DATA_DIR", str(tmp_path))
    assert main(["info"]) == 0
    out = capsys.readouterr().out
    assert "http://127.0.0.1:9000/mcp" in out
    assert "k" in out


def test_info_missing_state(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.setenv("CRAWL4AI_MCP_DATA_DIR", str(tmp_path))
    assert main(["info"]) == 1
    err = capsys.readouterr().err
    assert "start" in err.lower() or "serve" in err.lower()
