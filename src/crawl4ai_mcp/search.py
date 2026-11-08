"""SERP URL builders and HTML parsers for web_search."""

from __future__ import annotations

import base64
import binascii
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

from bs4 import BeautifulSoup

SUPPORTED_ENGINES = ("duckduckgo", "bing", "google")

_ENGINE_HOST_MARKERS = {
    "duckduckgo": ("duckduckgo.com",),
    "bing": ("bing.com",),
    "google": ("google.", "googleusercontent."),
}


def build_serp_url(engine: str, query: str) -> str:
    engine = engine.strip().lower()
    q = quote_plus(query.strip())
    if engine == "duckduckgo":
        return f"https://html.duckduckgo.com/html/?q={q}"
    if engine == "bing":
        return f"https://www.bing.com/search?q={q}"
    if engine == "google":
        return f"https://www.google.com/search?q={q}&hl=en&num=10"
    raise ValueError(f"Unsupported search engine: {engine}")


def _abs(base: str, href: str) -> str:
    href = (href or "").strip()
    if not href or href.startswith(("#", "javascript:", "mailto:")):
        return ""
    return urljoin(base, href)


def _clean_text(node) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def _unwrap_ddg_redirect(href: str) -> str:
    if "uddg=" not in href:
        return href
    qs = parse_qs(urlparse(href).query)
    return (qs.get("uddg") or [href])[0]


def _unwrap_google_redirect(href: str) -> str:
    parsed = urlparse(href)
    if parsed.path.startswith("/url") or "google." in parsed.netloc:
        qs = parse_qs(parsed.query)
        for key in ("q", "url"):
            vals = qs.get(key) or []
            if vals and vals[0].startswith(("http://", "https://")):
                return vals[0]
    return href


def _unwrap_bing_redirect(href: str) -> str:
    parsed = urlparse(href)
    if "bing.com" not in parsed.netloc:
        return href
    qs = parse_qs(parsed.query)
    raw = (qs.get("u") or [""])[0]
    if not raw:
        return href
    raw = unquote(raw)
    if raw.startswith("a1"):
        raw = raw[2:]
    pad = "=" * ((4 - len(raw) % 4) % 4)
    try:
        decoded = base64.urlsafe_b64decode(raw + pad).decode("utf-8", "ignore")
    except (binascii.Error, ValueError):
        return href
    if decoded.startswith(("http://", "https://")):
        return decoded
    return href


def _is_engine_host(engine: str, url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(marker in host for marker in _ENGINE_HOST_MARKERS.get(engine, ()))


def parse_serp_html(engine: str, html: str, *, max_results: int = 8, base_url: str = "") -> list[dict]:
    engine = engine.strip().lower()
    soup = BeautifulSoup(html or "", "lxml")
    results: list[dict] = []
    seen: set[str] = set()

    def add(title: str, url: str, snippet: str = "") -> None:
        if not title or not url:
            return
        if not url.startswith(("http://", "https://")):
            return
        if _is_engine_host(engine, url):
            return
        if url in seen:
            return
        seen.add(url)
        results.append({"title": title, "url": url, "snippet": snippet})

    if engine == "duckduckgo":
        base = base_url or "https://html.duckduckgo.com/"
        for block in soup.select(".result, .results_links, .web-result"):
            a = block.select_one("a.result__a")
            if not a:
                continue
            href = _unwrap_ddg_redirect(a.get("href") or "")
            snippet_el = block.select_one(".result__snippet")
            add(_clean_text(a), _abs(base, href), _clean_text(snippet_el))
            if len(results) >= max_results:
                break
    elif engine == "bing":
        base = base_url or "https://www.bing.com/"
        for block in soup.select("li.b_algo"):
            a = block.select_one("h2 a")
            if not a:
                continue
            href = _unwrap_bing_redirect(_abs(base, a.get("href") or ""))
            snippet_el = block.select_one(".b_caption p")
            add(_clean_text(a), href, _clean_text(snippet_el))
            if len(results) >= max_results:
                break
    elif engine == "google":
        base = base_url or "https://www.google.com/"
        for block in soup.select("div.g, div.MjjYud"):
            h3 = block.select_one("h3")
            a = block.select_one("a[href]")
            if not h3 or not a:
                continue
            href = _unwrap_google_redirect(_abs(base, a.get("href") or ""))
            snippet_el = block.select_one("div.VwiC3b, span.aCOpRe, div[data-sncf]")
            add(_clean_text(h3), href, _clean_text(snippet_el))
            if len(results) >= max_results:
                break
    else:
        raise ValueError(f"Unsupported search engine: {engine}")

    return results[:max_results]
