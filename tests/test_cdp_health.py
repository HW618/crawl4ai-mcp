import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from crawl4ai_mcp.crawler import (
    CdpConfigError,
    is_valid_cdp,
    normalize_cdp_url,
    require_cdp_url,
)
from crawl4ai_mcp.server import configure_logging, serve


def test_require_cdp_url_keeps_websocket_debugger_url():
    url = "ws://127.0.0.1:9222/devtools/browser/abc"
    assert require_cdp_url({"CDP_URL": url}) == url


def test_require_cdp_url_maps_bare_websocket_to_http():
    assert normalize_cdp_url("ws://127.0.0.1:9222/") == "http://127.0.0.1:9222"
    assert require_cdp_url({"CDP_URL": "wss://browser.internal:9443"}) == "https://browser.internal:9443"


def test_is_valid_cdp_accepts_websocket_upgrade():
    ready = threading.Event()
    holder: dict[str, int] = {}

    def _serve() -> None:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        holder["port"] = sock.getsockname()[1]
        ready.set()
        conn, _ = sock.accept()
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
        conn.sendall(
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n\r\n"
        )
        conn.close()
        sock.close()

    threading.Thread(target=_serve, daemon=True).start()
    assert ready.wait(2)
    url = f"ws://127.0.0.1:{holder['port']}/devtools/browser/abc"
    assert is_valid_cdp(url, timeout=2) is True


def test_configure_logging_includes_timestamp():
    import logging

    configure_logging()
    formats = [
        handler.formatter._fmt
        for handler in logging.getLogger().handlers
        if getattr(handler, "_crawl4ai_mcp_log", False) and handler.formatter is not None
    ]
    assert formats
    assert all("%(asctime)s" in fmt for fmt in formats)


def test_serve_persists_api_key_and_exits_when_cdp_is_down(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CDP_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("CRAWL4AI_MCP_DATA_DIR", str(tmp_path))
    with pytest.raises(SystemExit) as exc:
        serve()
    assert exc.value.code == 1
    saved = json.loads((tmp_path / "credentials.json").read_text(encoding="utf-8"))
    assert saved["api_key"]


def test_serve_checks_cdp_once_at_startup(tmp_path: Path, monkeypatch):
    calls: list[str] = []

    def _ready() -> str:
        calls.append("checked")
        return "http://127.0.0.1:9222"

    monkeypatch.setenv("CDP_URL", "http://127.0.0.1:9222")
    monkeypatch.setenv("CRAWL4AI_MCP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CDP_CHECK_INTERVAL_SEC", "0.01")
    monkeypatch.setattr("crawl4ai_mcp.server.assert_cdp_ready", _ready)
    monkeypatch.setattr("crawl4ai_mcp.server.uvicorn.run", lambda *args, **kwargs: None)
    before = {thread.name for thread in threading.enumerate()}
    serve()
    started = {thread.name for thread in threading.enumerate()} - before
    assert calls == ["checked"]
    assert "cdp-watch" not in started


def test_http_cdp_version_endpoint_is_accepted():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = json.dumps(
                {"webSocketDebuggerUrl": "ws://127.0.0.1:9/devtools/browser/x"}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert is_valid_cdp(f"http://127.0.0.1:{port}", timeout=2) is True
    finally:
        server.shutdown()


def test_require_cdp_url_rejects_unknown_scheme():
    with pytest.raises(CdpConfigError):
        require_cdp_url({"CDP_URL": "ftp://127.0.0.1:9222"})
