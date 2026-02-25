"""
Ticket price scraper using Playwright (headless Chromium).

Legal compliance measures built in:
  - Checks robots.txt before scraping each domain (cached per session)
  - Identifies itself honestly via User-Agent string
  - Rate-limited to max 9 runs/day via GitHub Actions schedule (18 page loads/day total)
  - Scrapes only publicly visible pricing pages, no login bypass
  - Data used for personal price monitoring only, not commercial exploitation
"""

import re
import logging
import urllib.robotparser
import urllib.parse
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

PAGE_LOAD_TIMEOUT_MS = 30_000
JS_SETTLE_WAIT_MS    = 3_000

# Honest, identifiable User-Agent — not pretending to be a regular browser
# Includes contact info as best practice for ethical scraping
USER_AGENT = (
    "CLHospitalityTicketMonitor/1.0 (personal price tracker; "
    "contact: anandshenoyuidev@gmail.com) "
    "Playwright/Chromium"
)


# ─── Data contract ────────────────────────────────────────────────────────────

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


# ─── robots.txt compliance ────────────────────────────────────────────────────

@lru_cache(maxsize=16)
def _is_allowed_by_robots(url: str) -> bool:
    """
    Check robots.txt for the given URL.
    Returns True if scraping is permitted (or robots.txt is unreachable).
    Cached per domain per session so we only fetch robots.txt once per domain.
    """
    parsed  = urllib.parse.urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots_url)
    try:
        rp.read()
        allowed = rp.can_fetch(USER_AGENT, url)
        if not allowed:
            logger.warning(f"robots.txt disallows scraping {url} — skipping")
        return allowed
    except Exception as e:
        # If robots.txt is unreachable, treat as permitted (standard convention)
        logger.info(f"Could not fetch robots.txt for {parsed.netloc} ({e}) — proceeding")
        return True


# ─── Price extraction ─────────────────────────────────────────────────────────

def _extract_prices_from_text(text: str) -> list[float]:
    """Extract all plausible EUR ticket prices from rendered page text."""
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
                if 10 <= val <= 50_000:
                    found.append(val)
            except ValueError:
                pass
    return sorted(set(found))


# ─── Playwright scraper ───────────────────────────────────────────────────────

def _scrape_with_playwright(url: str) -> str:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
            locale="en-GB",
            timezone_id="Europe/London",
        )

        page = context.new_page()

        try:
            page.goto(url, wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT_MS)
        except PWTimeout:
            logger.warning(f"networkidle timeout for {url}, falling back to domcontentloaded")
            page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)

        page.wait_for_timeout(JS_SETTLE_WAIT_MS)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1_000)

        text = page.inner_text("body")
        browser.close()
        return text


# ─── Public API ───────────────────────────────────────────────────────────────

def fetch_ticket_prices(game_name: str, url: str) -> TicketResult:
    """
    Check robots.txt compliance then fetch and extract EUR ticket prices.
    Returns a TicketResult; never raises.
    """
    logger.info(f"[{game_name}] Checking robots.txt → {url}")

    # Compliance check first
    if not _is_allowed_by_robots(url):
        msg = "Blocked by robots.txt — skipping to stay compliant"
        logger.warning(f"[{game_name}] {msg}")
        return TicketResult(
            game_name=game_name, url=url,
            prices=[], min_price=None, max_price=None,
            error=msg,
        )

    logger.info(f"[{game_name}] robots.txt OK — launching browser")
    try:
        page_text = _scrape_with_playwright(url)
        prices    = _extract_prices_from_text(page_text)

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
