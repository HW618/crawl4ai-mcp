import json
from unittest.mock import MagicMock, patch

import pytest

from crawl4ai_mcp.crawler import (
    CdpConfigError,
    crawl_page,
    is_valid_cdp,
    require_cdp_url,
)
from crawl4ai_mcp.models import SiteStrategy


def test_require_cdp_url_missing():
    with pytest.raises(CdpConfigError):
        require_cdp_url({})


def test_require_cdp_url_reads_env():
    assert require_cdp_url({"CDP_URL": " http://127.0.0.1:9222/ "}) == "http://127.0.0.1:9222"


def test_is_valid_cdp_rejects_bad():
    assert is_valid_cdp("not-a-url") is False
    with patch("crawl4ai_mcp.crawler.urllib.request.urlopen", side_effect=OSError("down")):
        assert is_valid_cdp("http://127.0.0.1:9222") is False


def test_is_valid_cdp_accepts_version_payload():
    payload = json.dumps({"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/x"}).encode()
    resp = MagicMock()
    resp.status = 200
    resp.read.return_value = payload
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    with patch("crawl4ai_mcp.crawler.urllib.request.urlopen", return_value=resp):
        assert is_valid_cdp("http://127.0.0.1:9222") is True


@pytest.mark.asyncio
async def test_crawl_page_does_not_fallback():
    strategies = [SiteStrategy(name="普通网页", domains=(), source="builtin")]

    class Boom:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise ConnectionError("CDP connect failed")

        async def __aexit__(self, *args):
            return False

    with patch("crawl4ai_mcp.crawler.AsyncWebCrawler", Boom):
        with patch("crawl4ai_mcp.crawler.assert_cdp_ready", return_value="http://127.0.0.1:9222"):
            result = await crawl_page(
                "https://example.com/",
                strategies,
                cdp_url="http://127.0.0.1:9222",
            )
    assert result.success is False
    assert "cdp" in result.error.lower() or "connect" in result.error.lower()
