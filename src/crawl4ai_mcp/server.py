from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount
from starlette.types import ASGIApp, Receive, Scope, Send

from .credentials import (
    data_dir_from_env,
    resolve_api_key,
    write_connection_json,
)
from .crawler import assert_cdp_ready
from .models import SiteStrategy
from .strategies import load_strategies
from .tools import tool_convert_url, tool_extract_summary, tool_list_site_strategies

logger = logging.getLogger(__name__)

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIGS = PACKAGE_ROOT / "configs"


class BearerAuthMiddleware:
    def __init__(self, app: ASGIApp, api_key: str):
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = {
                k.decode("latin-1").lower(): v.decode("latin-1")
                for k, v in scope.get("headers", [])
            }
            auth = headers.get("authorization", "")
            expected = f"Bearer {self.api_key}"
            if auth != expected:
                response = JSONResponse({"error": "unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_mcp(strategies: list[SiteStrategy], *, cdp_url: str | None = None) -> MCPServer:
    mcp = MCPServer("crawl4ai-mcp")

    @mcp.tool()
    async def convert_url(
        url: str,
        include_metadata: bool = True,
        include_images: bool = True,
        include_links: bool = True,
        timeout_sec: int = 45,
    ) -> str:
        """Convert a web page URL to Markdown using site strategies and CDP."""
        return await tool_convert_url(
            url,
            strategies=strategies,
            include_metadata=include_metadata,
            include_images=include_images,
            include_links=include_links,
            timeout_sec=timeout_sec,
            cdp_url=cdp_url,
        )

    @mcp.tool()
    async def extract_summary(url: str, max_length: int = 3000, timeout_sec: int = 45) -> str:
        """Extract a plain-text summary from a web page URL."""
        return await tool_extract_summary(
            url,
            strategies=strategies,
            max_length=max_length,
            timeout_sec=timeout_sec,
            cdp_url=cdp_url,
        )

    @mcp.tool()
    def list_site_strategies(filter: str | None = None) -> str:
        """List loaded site crawl/convert strategies."""
        return tool_list_site_strategies(strategies, filter=filter)

    return mcp


def _transport_security(advertise_host: str) -> TransportSecuritySettings:
    """Allow bind host with/without port, plus Starlette TestClient's testserver."""
    hosts = [
        advertise_host,
        f"{advertise_host}:*",
        "127.0.0.1",
        "127.0.0.1:*",
        "localhost",
        "localhost:*",
        "[::1]",
        "[::1]:*",
        "testserver",
        "testserver:*",
    ]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(dict.fromkeys(hosts)),
    )


def build_asgi_app(
    *,
    api_key: str,
    strategies: list[SiteStrategy],
    cdp_url: str | None = None,
    host: str = "127.0.0.1",
) -> Starlette:
    mcp = create_mcp(strategies, cdp_url=cdp_url)
    # Pass host so DNS-rebinding protection matches the advertised bind address.
    advertise_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    inner = mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        host=advertise_host,
        transport_security=_transport_security(advertise_host),
    )
    protected = BearerAuthMiddleware(inner, api_key=api_key)
    # Preserve MCP streamable HTTP lifespan (session manager task group).
    return Starlette(
        routes=[Mount("/", app=protected)],
        lifespan=inner.router.lifespan_context,
    )


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def serve() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cdp_url = assert_cdp_ready()
    host = os.environ.get("MCP_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = _env_int("MCP_PORT", 8000)
    path = "/mcp"
    data_dir = data_dir_from_env()
    api_key = resolve_api_key(os.environ, data_dir)
    user_dir = os.environ.get("CONFIG_DIR", "").strip() or None
    strategies = load_strategies(DEFAULT_CONFIGS, Path(user_dir) if user_dir else None)
    advertise_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    conn_path = write_connection_json(
        data_dir, host=advertise_host, port=port, path=path, api_key=api_key
    )
    url = f"http://{advertise_host}:{port}{path}"
    logger.info("MCP endpoint: %s", url)
    logger.info("API key: %s", api_key)
    logger.info("Connection JSON: %s", conn_path)
    logger.info("Loaded %d site strategies", len(strategies))
    app = build_asgi_app(
        api_key=api_key,
        strategies=strategies,
        cdp_url=cdp_url,
        host=advertise_host,
    )
    uvicorn.run(app, host=host, port=port, log_level="info")


def cmd_serve(_: argparse.Namespace) -> int:
    serve()
    return 0
