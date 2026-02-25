"""
run_once.py — single-shot scrape and alert.
Called by GitHub Actions on a schedule.
No loop, no sleep — runs once and exits.

Daily cap (10 alerts/day) is tracked via a GitHub Actions cache key
that resets automatically at midnight UTC.
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scraper import fetch_ticket_prices
from notifier import ResendEmailNotifier, build_ticket_alert_payload
import concurrent.futures

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("run_once")

# ─── Config ───────────────────────────────────────────────────────────────────
GAMES = [
    {
        "name": "Arsenal vs TBC (Champions League)",
        "url": "https://www.p1travel.com/en/football/champions-league/arsenal-vs-tbc-date-tbc",
    },
    {
        "name": "Manchester City vs TBC (Champions League)",
        "url": "https://www.p1travel.com/en/football/champions-league/manchester-city-vs-tbc-date-tbc",
    },
    {
        "name": "Chelsea vs TBC (Champions League)",
        "url": "https://champions-travel.com/tickets/uefa-champions-league?chelsea-v-tbc",
    },
]

THRESHOLD_LOW  = 100   # €
THRESHOLD_HIGH = 500   # €
RECIPIENT_EMAIL = "anand.shenoy14@gmail.com"
TIMEZONE = ZoneInfo("America/Los_Angeles")
ALERT_WINDOW_START = 9   # 9 AM PST
ALERT_WINDOW_END   = 17  # 5 PM PST
MAX_ALERTS_PER_DAY = 10

# GitHub Actions writes the daily count to this file,
# which is cached between runs via actions/cache
STATE_FILE = Path(os.environ.get("STATE_FILE", "alert_state.json"))


# ─── Alert window check ───────────────────────────────────────────────────────

def in_alert_window() -> bool:
    now = datetime.now(tz=TIMEZONE)
    return ALERT_WINDOW_START <= now.hour < ALERT_WINDOW_END


# ─── Daily count (file-based, cached by GitHub Actions) ──────────────────────

def get_daily_count() -> int:
    if not STATE_FILE.exists():
        return 0
    try:
        data = json.loads(STATE_FILE.read_text())
        today = datetime.now(tz=TIMEZONE).date().isoformat()
        if data.get("date") != today:
            return 0
        return data.get("count", 0)
    except Exception:
        return 0


def increment_daily_count() -> int:
    today = datetime.now(tz=TIMEZONE).date().isoformat()
    try:
        data = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    except Exception:
        data = {}
    if data.get("date") != today:
        data = {"date": today, "count": 0}
    data["count"] += 1
    STATE_FILE.write_text(json.dumps(data, indent=2))
    return data["count"]


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("=== Ticket Alert — single run ===")

    # 1. Check alert window
    if not in_alert_window():
        now = datetime.now(tz=TIMEZONE)
        logger.info(f"Outside alert window ({now.strftime('%H:%M')} PST). Exiting.")
        sys.exit(0)

    # 2. Check daily cap
    daily_count = get_daily_count()
    if daily_count >= MAX_ALERTS_PER_DAY:
        logger.info(f"Daily cap reached ({MAX_ALERTS_PER_DAY}). Exiting.")
        sys.exit(0)

    # 3. Scrape all games in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(GAMES)) as pool:
        futures = {pool.submit(fetch_ticket_prices, g["name"], g["url"]): g for g in GAMES}
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    # 4. Filter to in-range prices
    game_alerts = []
    for result in results:
        if result.error:
            logger.warning(f"[{result.game_name}] Error: {result.error}")
            continue
        if not result.has_prices:
            logger.info(f"[{result.game_name}] No prices found.")
            continue

        in_range = [p for p in result.prices if THRESHOLD_LOW <= p <= THRESHOLD_HIGH]
        logger.info(f"[{result.game_name}] All prices: {result.prices} | In range: {in_range}")

        if in_range:
            game_alerts.append({
                "game_name": result.game_name,
                "url": result.url,
                "prices_in_range": in_range,
                "min_price": min(in_range),
                "threshold_low": THRESHOLD_LOW,
                "threshold_high": THRESHOLD_HIGH,
            })

    # 5. Send alert if anything triggered
    if not game_alerts:
        logger.info("No in-range prices. No alert sent.")
        sys.exit(0)

    notifier = ResendEmailNotifier()  # reads RESEND_API_KEY from env
    payload = build_ticket_alert_payload(recipient=RECIPIENT_EMAIL, game_alerts=game_alerts)
    success = notifier.send(payload)

    if success:
        count = increment_daily_count()
        logger.info(f"Alert sent! Daily count: {count}/{MAX_ALERTS_PER_DAY}")
    else:
        logger.error("Alert failed to send.")
        sys.exit(1)


if __name__ == "__main__":
    main()
