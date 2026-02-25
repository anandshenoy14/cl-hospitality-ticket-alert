"""
run_once.py — single-shot scrape and alert.
Called by GitHub Actions on a schedule.

Alerting logic:
  - Both portals in range  → show comparison, highlight cheaper one
  - Only one portal in range → still alert, note the other portal's status
  - Neither portal in range  → no alert for that game
  - URL failed/no prices     → reported in the failed URLs section
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import concurrent.futures

from scraper import fetch_ticket_prices, TicketResult
from notifier import ResendEmailNotifier, build_ticket_alert_payload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("run_once")

# ─── Config ───────────────────────────────────────────────────────────────────

GAMES = [
    {
        "name": "Arsenal vs TBC",
        "p1travel_url": "https://www.p1travel.com/en/football/champions-league/arsenal-vs-tbc-date-tbc",
        "champions_travel_url": "https://champions-travel.com/tickets/uefa-champions-league?arsenal-v-tbc",
    },
    {
        "name": "Manchester City vs TBC",
        "p1travel_url": "https://www.p1travel.com/en/football/champions-league/manchester-city-vs-tbc-date-tbc",
        "champions_travel_url": "https://champions-travel.com/tickets/uefa-champions-league?manchester-city-v-tbc",
    },
    {
        "name": "Chelsea vs TBC",
        "p1travel_url": "https://www.p1travel.com/en/football/champions-league/chelsea-vs-tbc-date-tbc",
        "champions_travel_url": "https://champions-travel.com/tickets/uefa-champions-league?chelsea-v-tbc",
    },
]

THRESHOLD_LOW      = 100
THRESHOLD_HIGH     = 500
RECIPIENT_EMAIL    = "anandshenoyuidev@gmail.com"
TIMEZONE           = ZoneInfo("America/Los_Angeles")
ALERT_WINDOW_START = 9
ALERT_WINDOW_END   = 17
MAX_ALERTS_PER_DAY = 10

STATE_FILE = Path(os.environ.get("STATE_FILE", "alert_state.json"))


# ─── Alert window & daily cap ─────────────────────────────────────────────────

def in_alert_window() -> bool:
    now = datetime.now(tz=TIMEZONE)
    return ALERT_WINDOW_START <= now.hour < ALERT_WINDOW_END


def get_daily_count() -> int:
    if not STATE_FILE.exists():
        return 0
    try:
        data = json.loads(STATE_FILE.read_text())
        today = datetime.now(tz=TIMEZONE).date().isoformat()
        return data.get("count", 0) if data.get("date") == today else 0
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


# ─── Helpers ──────────────────────────────────────────────────────────────────

def cheapest_in_range(result: TicketResult | None) -> float | None:
    if not result or result.error or not result.prices:
        return None
    in_range = [p for p in result.prices if THRESHOLD_LOW <= p <= THRESHOLD_HIGH]
    return min(in_range) if in_range else None


def portal_status(result: TicketResult | None, url: str) -> dict:
    """Summarise a portal scrape into a clean status dict."""
    if result is None:
        return {"ok": False, "reason": "No result returned", "url": url}
    if result.error:
        return {"ok": False, "reason": result.error, "url": url}
    if not result.prices:
        return {"ok": False, "reason": "Page loaded but no prices found", "url": url}
    best = cheapest_in_range(result)
    if best is None:
        return {"ok": False, "reason": f"Prices found but none in €{THRESHOLD_LOW}–€{THRESHOLD_HIGH}", "url": url}
    return {"ok": True, "best": best, "url": url}


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("=== CL Hospitality Ticket Alert — single run ===")

    if not in_alert_window():
        now = datetime.now(tz=TIMEZONE)
        logger.info(f"Outside alert window ({now.strftime('%H:%M')} PST). Exiting.")
        sys.exit(0)

    if get_daily_count() >= MAX_ALERTS_PER_DAY:
        logger.info(f"Daily cap reached ({MAX_ALERTS_PER_DAY}). Exiting.")
        sys.exit(0)

    # Scrape all URLs in parallel
    scrape_tasks = [
        (game["name"], "P1 Travel",        game["p1travel_url"])
        for game in GAMES
    ] + [
        (game["name"], "Champions Travel",  game["champions_travel_url"])
        for game in GAMES
    ]

    raw: dict[str, dict[str, TicketResult]] = {g["name"]: {} for g in GAMES}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(scrape_tasks)) as pool:
        futures = {
            pool.submit(fetch_ticket_prices, f"{name} ({portal})", url): (name, portal)
            for name, portal, url in scrape_tasks
        }
        for future in concurrent.futures.as_completed(futures):
            name, portal = futures[future]
            raw[name][portal] = future.result()

    # Evaluate each game
    game_alerts = []   # at least one portal has in-range prices
    failed_urls = []   # portals that errored or had no usable prices

    for game in GAMES:
        name   = game["name"]
        p1_status     = portal_status(raw[name].get("P1 Travel"),       game["p1travel_url"])
        champs_status = portal_status(raw[name].get("Champions Travel"), game["champions_travel_url"])

        p1_ok     = p1_status["ok"]
        champs_ok = champs_status["ok"]

        logger.info(
            f"[{name}] P1 Travel: {'€' + str(int(p1_status['best'])) if p1_ok else p1_status['reason']} | "
            f"Champions Travel: {'€' + str(int(champs_status['best'])) if champs_ok else champs_status['reason']}"
        )

        # Collect failed portals
        for portal_name, status in [("P1 Travel", p1_status), ("Champions Travel", champs_status)]:
            if not status["ok"]:
                failed_urls.append({
                    "game_name": name,
                    "portal":    portal_name,
                    "url":       status["url"],
                    "reason":    status["reason"],
                })

        # Skip game entirely if neither portal has in-range prices
        if not p1_ok and not champs_ok:
            logger.info(f"[{name}] Neither portal has in-range prices. Skipping.")
            continue

        # Build alert entry — works for one portal or both
        alert = {
            "game_name":            name,
            "p1travel_url":         game["p1travel_url"],
            "champions_travel_url": game["champions_travel_url"],
            "p1_best":              p1_status.get("best"),       # None if failed
            "champs_best":          champs_status.get("best"),   # None if failed
            "threshold_low":        THRESHOLD_LOW,
            "threshold_high":       THRESHOLD_HIGH,
        }

        # Determine cheaper / only available portal
        if p1_ok and champs_ok:
            alert["cheaper_portal"] = "P1 Travel" if p1_status["best"] <= champs_status["best"] else "Champions Travel"
            alert["saving"]         = abs(p1_status["best"] - champs_status["best"])
            alert["comparison"]     = "both"
        elif p1_ok:
            alert["cheaper_portal"] = "P1 Travel"
            alert["saving"]         = None
            alert["comparison"]     = "p1_only"
        else:
            alert["cheaper_portal"] = "Champions Travel"
            alert["saving"]         = None
            alert["comparison"]     = "champs_only"

        game_alerts.append(alert)

    if not game_alerts and not failed_urls:
        logger.info("No in-range prices and no failures. No alert sent.")
        sys.exit(0)

    notifier = ResendEmailNotifier()
    payload  = build_ticket_alert_payload(
        recipient=RECIPIENT_EMAIL,
        game_alerts=game_alerts,
        failed_urls=failed_urls,
        threshold_low=THRESHOLD_LOW,
        threshold_high=THRESHOLD_HIGH,
    )
    success = notifier.send(payload)

    if success:
        count = increment_daily_count()
        logger.info(f"Alert sent! Daily count: {count}/{MAX_ALERTS_PER_DAY}")
    else:
        logger.error("Alert failed to send.")
        sys.exit(1)


if __name__ == "__main__":
    main()
