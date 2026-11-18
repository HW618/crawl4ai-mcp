from crawl4ai_mcp.search import (
    SUPPORTED_ENGINES,
    build_serp_url,
    parse_serp_html,
)


def test_supported_engines():
    assert "duckduckgo" in SUPPORTED_ENGINES
    assert "bing" in SUPPORTED_ENGINES
    assert "google" in SUPPORTED_ENGINES


def test_build_serp_url_encodes_query():
    url = build_serp_url("duckduckgo", "hello world")
    assert "duckduckgo.com" in url
    assert "hello" in url


def test_parse_duckduckgo_fixture():
    html = """
    <html><body>
      <div class="result results_links">
        <a class="result__a" href="https://example.com/a">Alpha</a>
        <a class="result__snippet">Snippet A</a>
      </div>
      <div class="result results_links">
        <a class="result__a" href="https://example.com/b">Beta</a>
        <div class="result__snippet">Snippet B</div>
      </div>
    </body></html>
    """
    rows = parse_serp_html("duckduckgo", html, max_results=10)
    assert len(rows) == 2
    assert rows[0]["title"] == "Alpha"
    assert rows[0]["url"] == "https://example.com/a"
    assert "Snippet A" in rows[0]["snippet"]


def test_parse_bing_fixture():
    html = """
    <html><body>
      <li class="b_algo">
        <h2><a href="https://example.com/bing">Bing Hit</a></h2>
        <div class="b_caption"><p>Bing snippet</p></div>
      </li>
    </body></html>
    """
    rows = parse_serp_html("bing", html, max_results=5)
    assert len(rows) == 1
    assert rows[0]["url"] == "https://example.com/bing"
    assert rows[0]["title"] == "Bing Hit"


def test_parse_bing_unwraps_ck_redirect():
    html = """
    <html><body>
      <li class="b_algo">
        <h2><a href="https://www.bing.com/ck/a?&amp;u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS9iaW5nLXJlYWw">Bing Redirect</a></h2>
        <div class="b_caption"><p>snippet</p></div>
      </li>
    </body></html>
    """
    # Bing often base64-url encodes the destination after a leading 'a1'
    rows = parse_serp_html("bing", html, max_results=5)
    assert len(rows) == 1
    assert rows[0]["url"] == "https://example.com/bing-real"


def test_parse_google_fixture():
    html = """
    <html><body>
      <div class="g">
        <a href="https://example.com/g"><h3>Google Hit</h3></a>
        <div class="VwiC3b">Google snippet</div>
      </div>
    </body></html>
    """
    rows = parse_serp_html("google", html, max_results=5)
    assert len(rows) >= 1
    assert rows[0]["url"].startswith("https://example.com/g")
    assert "Google Hit" in rows[0]["title"]


def test_parse_google_unwraps_url_redirect():
    html = """
    <html><body>
      <div class="g">
        <a href="/url?q=https://example.com/real&amp;sa=U"><h3>Google Redirect</h3></a>
        <div class="VwiC3b">snippet</div>
      </div>
    </body></html>
    """
    rows = parse_serp_html("google", html, max_results=5)
    assert len(rows) == 1
    assert rows[0]["url"] == "https://example.com/real"
