"""
run_once.py — single-shot scrape and alert.
Called by GitHub Actions on a schedule.

For each game, compares prices across two portals (P1 Travel and Champions Travel).
Alert fires only when BOTH portals have a price within the threshold range.
Email shows the cheapest price from each portal and highlights which is cheaper.
Failed or unreachable URLs are reported in the email as a separate section.
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


# ─── Price helpers ────────────────────────────────────────────────────────────

def cheapest_in_range(result: TicketResult) -> float | None:
    in_range = [p for p in result.prices if THRESHOLD_LOW <= p <= THRESHOLD_HIGH]
    return min(in_range) if in_range else None


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("=== CL Hospitality Ticket Alert — single run ===")

    if not in_alert_window():
        now = datetime.now(tz=TIMEZONE)
        logger.info(f"Outside alert window ({now.strftime('%H:%M')} PST). Exiting.")
        sys.exit(0)

    daily_count = get_daily_count()
    if daily_count >= MAX_ALERTS_PER_DAY:
        logger.info(f"Daily cap reached ({MAX_ALERTS_PER_DAY}). Exiting.")
        sys.exit(0)

    # Build flat list of all scrape tasks — 2 per game
    scrape_tasks = [
        (game["name"], "P1 Travel",       game["p1travel_url"])
        for game in GAMES
    ] + [
        (game["name"], "Champions Travel", game["champions_travel_url"])
        for game in GAMES
    ]

    # Scrape all URLs in parallel
    results: dict[str, dict[str, TicketResult]] = {g["name"]: {} for g in GAMES}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(scrape_tasks)) as pool:
        futures = {
            pool.submit(fetch_ticket_prices, f"{name} ({portal})", url): (name, portal)
            for name, portal, url in scrape_tasks
        }
        for future in concurrent.futures.as_completed(futures):
            name, portal = futures[future]
            results[name][portal] = future.result()

    # Categorise each game into: alert, skipped (one portal ok), or failed
    game_alerts  = []  # both portals in range
    failed_urls  = []  # one or both portals errored or returned no prices

    for game in GAMES:
        name   = game["name"]
        p1     = results[name].get("P1 Travel")
        champs = results[name].get("Champions Travel")

        # Collect any failures for this game
        game_failures = []
        if not p1 or p1.error:
            reason = p1.error if p1 else "No result returned"
            game_failures.append({
                "game_name": name,
                "portal": "P1 Travel",
                "url": game["p1travel_url"],
                "reason": reason,
            })
            logger.warning(f"[{name}] P1 Travel failed: {reason}")

        if not champs or champs.error:
            reason = champs.error if champs else "No result returned"
            game_failures.append({
                "game_name": name,
                "portal": "Champions Travel",
                "url": game["champions_travel_url"],
                "reason": reason,
            })
            logger.warning(f"[{name}] Champions Travel failed: {reason}")

        failed_urls.extend(game_failures)

        # Only compare prices if both portals loaded successfully
        if game_failures:
            continue

        p1_best    = cheapest_in_range(p1)
        champs_best = cheapest_in_range(champs)

        logger.info(
            f"[{name}] P1 Travel best: {f'€{p1_best:.0f}' if p1_best else 'none in range'} | "
            f"Champions Travel best: {f'€{champs_best:.0f}' if champs_best else 'none in range'}"
        )

        if p1_best is None or champs_best is None:
            logger.info(f"[{name}] One or both portals have no in-range price. Skipping.")
            continue

        cheaper_portal = "P1 Travel" if p1_best <= champs_best else "Champions Travel"
        saving         = abs(p1_best - champs_best)

        game_alerts.append({
            "game_name":             name,
            "p1travel_url":          game["p1travel_url"],
            "champions_travel_url":  game["champions_travel_url"],
            "p1_best":               p1_best,
            "champs_best":           champs_best,
            "cheaper_portal":        cheaper_portal,
            "cheaper_price":         min(p1_best, champs_best),
            "saving":                saving,
            "threshold_low":         THRESHOLD_LOW,
            "threshold_high":        THRESHOLD_HIGH,
        })

    # Always send an email if there are alerts OR failures to report
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
