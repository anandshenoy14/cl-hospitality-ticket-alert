"""
Ticket price scraper using Playwright (headless Chromium).
Handles JavaScript-rendered pages that a plain requests/BeautifulSoup
scraper cannot see.

Install once:
    pip install playwright
    playwright install chromium --with-deps
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

# How long to wait for the page to fully load (ms)
PAGE_LOAD_TIMEOUT_MS = 30_000

# After initial load, extra wait for JS to finish rendering prices (ms)
JS_SETTLE_WAIT_MS = 3_000

# Realistic browser fingerprint – avoids basic bot detection
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# ─── Data contract (unchanged – scheduler.py depends on this) ─────────────────

@dataclass
class TicketResult:
    game_name: str
    url: str
    prices: list[float]
    min_price: Optional[float]
    max_price: Optional[float]
    currency: str = "EUR"
    error: Optional[str] = None

    @property
    def has_prices(self) -> bool:
        return bool(self.prices)


# ─── Price extraction (same regex logic, now fed full rendered HTML) ──────────

def _extract_prices_from_text(text: str) -> list[float]:
    """
    Extract all plausible EUR ticket prices from rendered page text.
    Matches: €150, €1,200, EUR 150, 150€, 150 EUR
    """
    patterns = [
        r"€\s*([\d,]+(?:\.\d{1,2})?)",
        r"EUR\s*([\d,]+(?:\.\d{1,2})?)",
        r"([\d,]+(?:\.\d{1,2})?)\s*€",
        r"([\d,]+(?:\.\d{1,2})?)\s*EUR",
    ]
    found = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            raw = match.group(1).replace(",", "")
            try:
                val = float(raw)
                # Sanity range: real ticket prices are between €10 and €50,000
                if 10 <= val <= 50_000:
                    found.append(val)
            except ValueError:
                pass
    return sorted(set(found))


# ─── Playwright scraper ───────────────────────────────────────────────────────

def _scrape_with_playwright(url: str) -> str:
    """
    Launch headless Chromium, navigate to URL, wait for JS to settle,
    and return the full rendered page text (visible text only).
    """
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",   # important inside Docker
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
            locale="en-GB",                  # ticket sites often serve EUR for en-GB
            timezone_id="Europe/London",
        )

        # Hide webdriver flag (basic anti-bot measure)
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        page = context.new_page()

        try:
            # Wait until network is idle (all XHR/fetch calls complete)
            page.goto(url, wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT_MS)
        except PWTimeout:
            # networkidle timed out – fall back to domcontentloaded
            logger.warning(f"networkidle timeout for {url}, falling back to domcontentloaded")
            page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)

        # Extra pause for React/Vue/Angular hydration and lazy-loaded price widgets
        page.wait_for_timeout(JS_SETTLE_WAIT_MS)

        # Scroll to bottom to trigger any scroll-based lazy loading
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1_000)

        text = page.inner_text("body")
        browser.close()
        return text


# ─── Public API (called by scheduler.py) ─────────────────────────────────────

def fetch_ticket_prices(game_name: str, url: str) -> TicketResult:
    """
    Fetch fully rendered page via Playwright and extract EUR ticket prices.
    Returns a TicketResult; never raises.
    """
    logger.info(f"[{game_name}] Launching browser → {url}")
    try:
        page_text = _scrape_with_playwright(url)
        prices = _extract_prices_from_text(page_text)

        if not prices:
            logger.info(f"[{game_name}] No prices found in rendered text.")
        else:
            logger.info(f"[{game_name}] Prices found: {prices}")

        return TicketResult(
            game_name=game_name,
            url=url,
            prices=prices,
            min_price=min(prices) if prices else None,
            max_price=max(prices) if prices else None,
        )

    except PWTimeout as e:
        msg = f"Page load timed out: {e}"
        logger.warning(f"[{game_name}] {msg}")
        return TicketResult(game_name=game_name, url=url, prices=[], min_price=None, max_price=None, error=msg)

    except Exception as e:
        logger.exception(f"[{game_name}] Unexpected scraper error")
        return TicketResult(game_name=game_name, url=url, prices=[], min_price=None, max_price=None, error=str(e))
