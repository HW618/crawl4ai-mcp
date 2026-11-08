import json
import os
from pathlib import Path

from crawl4ai_mcp.credentials import (
    load_connection,
    resolve_api_key,
    write_connection_json,
)


def test_resolve_api_key_generates_and_persists(tmp_path: Path):
    key1 = resolve_api_key({}, tmp_path)
    key2 = resolve_api_key({}, tmp_path)
    assert key1 == key2
    assert len(key1) >= 20
    assert (tmp_path / "credentials.json").is_file()


def test_resolve_api_key_uses_env_and_persists(tmp_path: Path):
    key = resolve_api_key({"API_KEY": "fixed-test-key"}, tmp_path)
    assert key == "fixed-test-key"
    assert json.loads((tmp_path / "credentials.json").read_text())["api_key"] == "fixed-test-key"


def test_write_and_load_connection_json(tmp_path: Path):
    path = write_connection_json(
        tmp_path,
        host="127.0.0.1",
        port=8000,
        path="/mcp",
        api_key="abc",
    )
    data = load_connection(tmp_path)
    assert path.name == "connection.json"
    assert data["transport"] == "streamable-http"
    assert data["url"] == "http://127.0.0.1:8000/mcp"
    assert data["api_key"] == "abc"
    assert data["authorization"] == "Bearer abc"
    assert "updated_at" in data
