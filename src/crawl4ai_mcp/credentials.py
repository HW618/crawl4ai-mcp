from __future__ import annotations

import json
import os
import secrets
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DATA_DIR = Path.home() / ".crawl4ai-mcp"
CREDENTIALS_NAME = "credentials.json"
CONNECTION_NAME = "connection.json"


def data_dir_from_env(env: Mapping[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    raw = source.get("CRAWL4AI_MCP_DATA_DIR", "").strip()
    return Path(raw) if raw else DEFAULT_DATA_DIR


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def resolve_api_key(env: Mapping[str, str], data_dir: Path) -> str:
    data_dir.mkdir(parents=True, exist_ok=True)
    cred_path = data_dir / CREDENTIALS_NAME
    env_key = str(env.get("API_KEY", "")).strip()
    if env_key:
        cred_path.write_text(
            json.dumps({"api_key": env_key}, indent=2) + "\n",
            encoding="utf-8",
        )
        return env_key
    existing = _read_json(cred_path)
    if existing and isinstance(existing.get("api_key"), str) and existing["api_key"].strip():
        return existing["api_key"].strip()
    key = secrets.token_urlsafe(32)
    cred_path.write_text(json.dumps({"api_key": key}, indent=2) + "\n", encoding="utf-8")
    return key


def write_connection_json(
    data_dir: Path,
    *,
    host: str,
    port: int,
    path: str,
    api_key: str,
) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    if not path.startswith("/"):
        path = "/" + path
    url = f"http://{host}:{port}{path}"
    payload = {
        "transport": "streamable-http",
        "url": url,
        "api_key": api_key,
        "authorization": f"Bearer {api_key}",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    out = data_dir / CONNECTION_NAME
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out


def load_connection(data_dir: Path) -> dict | None:
    return _read_json(data_dir / CONNECTION_NAME)
