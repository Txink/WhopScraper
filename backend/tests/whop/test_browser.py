import os

import pytest

# Mark Playwright-launching tests so CI can opt-out via env var.
playwright_required = pytest.mark.skipif(
    os.environ.get("SKIP_PLAYWRIGHT") == "1",
    reason="Playwright tests skipped (SKIP_PLAYWRIGHT=1)",
)


@playwright_required
@pytest.mark.asyncio
async def test_browser_start_navigate_close(tmp_path):
    """Smoke test: launch Chromium, navigate to about:blank, close cleanly."""
    from app.whop.browser import WhopBrowser

    cookie = tmp_path / "cookie.json"
    browser = WhopBrowser(headless=True, cookie_path=str(cookie))
    page = await browser.start()
    assert page is not None
    ok = await browser.navigate("about:blank")
    assert ok
    html = await browser.scrape_html()
    assert "<html" in html.lower()
    await browser.close()


@playwright_required
@pytest.mark.asyncio
async def test_browser_loads_existing_cookie(tmp_path):
    """If cookie file exists, browser should load it as storage_state."""
    import json

    from app.whop.browser import WhopBrowser

    cookie_file = tmp_path / "cookie.json"
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    cookie_file.write_text(
        json.dumps(
            {
                "cookies": [],
                "origins": [],
            }
        )
    )

    browser = WhopBrowser(headless=True, cookie_path=str(cookie_file))
    page = await browser.start()
    # If we got here without exception, cookie state loaded successfully.
    assert page is not None
    await browser.close()
