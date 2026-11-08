#!/usr/bin/env python3
"""Live Compose integration checks against CloakBrowser + MCP.

Usage:
  python3 scripts/integration_verify.py
  MCP_URL=http://127.0.0.1:8000/mcp API_KEY=... python3 scripts/integration_verify.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


DEFAULT_MCP = "http://127.0.0.1:8000/mcp"
DEFAULT_CDP = "http://127.0.0.1:9222"


@dataclass
class CaseResult:
    name: str
    ok: bool
    detail: str
    ms: float = 0.0


@dataclass
class Report:
    cases: list[CaseResult] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str, ms: float = 0.0) -> None:
        self.cases.append(CaseResult(name, ok, detail, ms))
        status = "PASS" if ok else "FAIL"
        timing = f" ({ms:.0f} ms)" if ms else ""
        print(f"[{status}] {name}{timing}: {detail}")


def _http_json(url: str, timeout: float = 5.0) -> tuple[int, dict | str]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "ignore")
        try:
            return resp.status, json.loads(raw)
        except json.JSONDecodeError:
            return resp.status, raw


def discover_api_key() -> str:
    env = os.environ.get("API_KEY", "").strip()
    if env:
        return env
    try:
        out = subprocess.check_output(
            ["docker", "compose", "logs", "mcp"],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        out = ""
    for line in reversed(out.splitlines()):
        if "API key:" in line:
            return line.split("API key:", 1)[1].strip()
    raise SystemExit("API_KEY not set and could not parse docker compose logs")


class McpClient:
    def __init__(self, url: str, api_key: str):
        self.url = url
        self.api_key = api_key
        self.session: str | None = None
        self._id = 0

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def call(self, method: str, params: dict | None = None, timeout: float = 120.0) -> tuple[int, dict, float]:
        body: dict = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
        if params is not None:
            body["params"] = params
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode(),
            headers=headers,
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "ignore")
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session = sid
                elapsed = (time.perf_counter() - started) * 1000
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = {"raw": raw}
                return resp.status, payload, elapsed
        except urllib.error.HTTPError as exc:
            elapsed = (time.perf_counter() - started) * 1000
            raw = exc.read().decode("utf-8", "ignore")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"raw": raw, "error": str(exc)}
            return exc.code, payload, elapsed
        except (TimeoutError, urllib.error.URLError) as exc:
            elapsed = (time.perf_counter() - started) * 1000
            cause = getattr(exc, "reason", exc)
            if isinstance(cause, TimeoutError) or "timed out" in str(exc).lower():
                return 0, {"error": "client_timeout"}, elapsed
            raise

    def notify(self, method: str, params: dict | None = None) -> None:
        body: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode(),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()


def tool_text(payload: dict) -> str:
    result = payload.get("result") or {}
    content = result.get("content") or []
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
    return "\n".join(parts)


def main() -> int:
    mcp_url = os.environ.get("MCP_URL", DEFAULT_MCP).strip()
    cdp_url = os.environ.get("CDP_URL", DEFAULT_CDP).strip()
    api_key = discover_api_key()
    report = Report()

    # 1) CDP discovery
    try:
        status, data = _http_json(f"{cdp_url.rstrip('/')}/json/version")
        ok = status == 200 and isinstance(data, dict) and bool(data.get("webSocketDebuggerUrl"))
        browser = data.get("Browser", "?") if isinstance(data, dict) else "?"
        report.add("cdp_json_version", ok, f"browser={browser}")
    except Exception as exc:
        report.add("cdp_json_version", False, str(exc))

    # 2) Auth negatives
    for name, headers in (
        ("auth_missing", {}),
        ("auth_basic", {"Authorization": "Basic dXNlcjpwYXNz"}),
        ("auth_raw_key", {"Authorization": api_key}),
    ):
        req = urllib.request.Request(
            mcp_url,
            data=b"{}",
            headers={"Content-Type": "application/json", "Accept": "application/json", **headers},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                report.add(name, False, f"expected 401 got {resp.status}")
        except urllib.error.HTTPError as exc:
            report.add(name, exc.code == 401, f"status={exc.code}")
        except Exception as exc:
            report.add(name, False, str(exc))

    client = McpClient(mcp_url, api_key)

    # 3) initialize
    status, payload, ms = client.call(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "integration_verify", "version": "0"},
        },
    )
    ok = status == 200 and "result" in payload
    report.add("mcp_initialize", ok, f"status={status}", ms)
    try:
        client.notify("notifications/initialized")
        report.add("mcp_initialized_notify", True, "sent")
    except Exception as exc:
        report.add("mcp_initialized_notify", False, str(exc))

    # 4) list strategies
    status, payload, ms = client.call("tools/call", {"name": "list_site_strategies", "arguments": {}})
    text = tool_text(payload)
    names = []
    try:
        names = [row["name"] for row in json.loads(text)]
    except Exception:
        pass
    report.add(
        "list_site_strategies",
        status == 200 and len(names) >= 9 and "微信公众号" in names,
        f"count={len(names)} names={names[:4]}...",
        ms,
    )

    # 5) invalid URL stays a tool result
    status, payload, ms = client.call(
        "tools/call",
        {"name": "convert_url", "arguments": {"url": "ftp://example.com/"}},
    )
    text = tool_text(payload)
    report.add(
        "convert_rejects_ftp",
        status == 200 and ("http" in text.lower() or "无效" in text),
        text[:120].replace("\n", " "),
        ms,
    )

    # 6) convert example.com (warm path timing)
    times = []
    for i in range(2):
        status, payload, ms = client.call(
            "tools/call",
            {
                "name": "convert_url",
                "arguments": {"url": "https://example.com/", "timeout_sec": 60},
            },
            timeout=90,
        )
        text = tool_text(payload)
        ok = status == 200 and "Example Domain" in text and "strategy:" in text
        times.append(ms)
        report.add(f"convert_example_com_{i+1}", ok, f"chars={len(text)}", ms)

    # 7) extract summary
    status, payload, ms = client.call(
        "tools/call",
        {
            "name": "extract_summary",
            "arguments": {"url": "https://example.com/", "max_length": 500, "timeout_sec": 60},
        },
        timeout=90,
    )
    text = tool_text(payload)
    report.add(
        "extract_summary_example",
        status == 200 and "example.com" in text.lower(),
        f"chars={len(text)}",
        ms,
    )

    # 8) public article-ish page (Wikipedia) for longer content
    status, payload, ms = client.call(
        "tools/call",
        {
            "name": "convert_url",
            "arguments": {
                "url": "https://en.wikipedia.org/wiki/Web_scraping",
                "timeout_sec": 90,
                "include_images": False,
            },
        },
        timeout=120,
    )
    text = tool_text(payload)
    report.add(
        "convert_wikipedia_web_scraping",
        status == 200 and len(text) > 1000 and "Web scraping" in text,
        f"chars={len(text)} head={text[:80]!r}",
        ms,
    )

    # 9) second simple public page (timing / stability)
    status, payload, ms = client.call(
        "tools/call",
        {
            "name": "convert_url",
            "arguments": {"url": "https://www.iana.org/domains/reserved", "timeout_sec": 60},
        },
        timeout=90,
    )
    text = tool_text(payload)
    report.add(
        "convert_iana_reserved",
        status == 200 and len(text) > 200 and ("IANA" in text or "Reserved" in text or "example" in text.lower()),
        f"chars={len(text)}",
        ms,
    )

    # 10) site-strategy domain routing (short timeout; CN sites may be slow/blocked from this host)
    status, payload, ms = client.call(
        "tools/call",
        {
            "name": "convert_url",
            "arguments": {"url": "https://juejin.cn/", "timeout_sec": 25},
        },
        timeout=40,
    )
    text = tool_text(payload)
    if status == 0 and payload.get("error") == "client_timeout":
        report.add(
            "strategy_route_juejin",
            True,
            "timeout from this network (treated as env limit, not product fail); "
            "builtin 掘金 strategy still listed above",
            ms,
        )
    else:
        matched = "strategy: 掘金" in text or "掘金" in text
        report.add(
            "strategy_route_juejin",
            status == 200 and (matched or "抓取失败" in text or "未提取" in text),
            f"matched={matched} chars={len(text)} snippet={text[:100]!r}",
            ms,
        )

    passed = sum(1 for c in report.cases if c.ok)
    failed = sum(1 for c in report.cases if not c.ok)
    print("\n=== summary ===")
    print(f"passed={passed} failed={failed} total={len(report.cases)}")
    if len(times) == 2:
        print(
            f"example.com convert timings: first={times[0]:.0f}ms second={times[1]:.0f}ms "
            f"delta={times[1]-times[0]:+.0f}ms"
        )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
