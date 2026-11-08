from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from crawl4ai_mcp.server import BearerAuthMiddleware, build_asgi_app


async def _ok(request):
    return JSONResponse({"ok": True})


def _auth_client(api_key: str = "secret") -> TestClient:
    inner = Starlette(routes=[Route("/mcp", endpoint=_ok, methods=["POST"])])
    return TestClient(BearerAuthMiddleware(inner, api_key=api_key))


def test_missing_auth_is_401():
    resp = _auth_client().post("/mcp", json={})
    assert resp.status_code == 401


def test_basic_auth_is_401():
    resp = _auth_client().post("/mcp", json={}, headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert resp.status_code == 401


def test_raw_key_without_bearer_is_401():
    resp = _auth_client().post("/mcp", json={}, headers={"Authorization": "secret"})
    assert resp.status_code == 401


def test_bearer_key_not_401():
    resp = _auth_client().post("/mcp", json={}, headers={"Authorization": "Bearer secret"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_build_asgi_app_constructs():
    app = build_asgi_app(api_key="secret", strategies=[])
    assert app is not None


def test_build_asgi_app_initialize_not_500():
    app = build_asgi_app(api_key="secret", strategies=[])
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }
    # Context manager starts MCP streamable HTTP lifespan (session manager).
    with TestClient(app) as client:
        resp = client.post(
            "/mcp",
            json=payload,
            headers={
                "Authorization": "Bearer secret",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
    assert resp.status_code != 500, resp.text
    assert resp.status_code == 200, resp.text
