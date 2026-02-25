"""
run_once.py — scrapes prices and writes docs/data/prices.json.
GitHub Actions commits the updated file back to the repo,
which GitHub Pages then serves to the PWA.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import concurrent.futures

from scraper import fetch_ticket_prices, TicketResult

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

THRESHOLD_LOW   = 100
THRESHOLD_HIGH  = 500
OUTPUT_FILE     = Path("docs/data/prices.json")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def cheapest_in_range(result: TicketResult | None) -> float | None:
    if not result or result.error or not result.prices:
        return None
    in_range = [p for p in result.prices if THRESHOLD_LOW <= p <= THRESHOLD_HIGH]
    return min(in_range) if in_range else None


def portal_status(result: TicketResult | None, url: str) -> dict:
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
    logger.info("=== CL Hospitality Ticket Alert — scraping prices ===")

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

    # Build output
    games_out  = []
    failed_out = []

    for game in GAMES:
        name   = game["name"]
        p1_s   = portal_status(raw[name].get("P1 Travel"),       game["p1travel_url"])
        ch_s   = portal_status(raw[name].get("Champions Travel"), game["champions_travel_url"])

        p1_ok = p1_s["ok"]
        ch_ok = ch_s["ok"]

        logger.info(
            f"[{name}] P1: {'€' + str(int(p1_s['best'])) if p1_ok else p1_s['reason']} | "
            f"CT: {'€' + str(int(ch_s['best'])) if ch_ok else ch_s['reason']}"
        )

        # Collect failures
        for portal_name, status in [("P1 Travel", p1_s), ("Champions Travel", ch_s)]:
            if not status["ok"]:
                failed_out.append({
                    "game_name": name,
                    "portal":    portal_name,
                    "url":       status["url"],
                    "reason":    status["reason"],
                })

        # Determine comparison type
        if p1_ok and ch_ok:
            comparison     = "both"
            cheaper_portal = "P1 Travel" if p1_s["best"] <= ch_s["best"] else "Champions Travel"
            saving         = abs(p1_s["best"] - ch_s["best"])
        elif p1_ok:
            comparison     = "p1_only"
            cheaper_portal = "P1 Travel"
            saving         = None
        elif ch_ok:
            comparison     = "champs_only"
            cheaper_portal = "Champions Travel"
            saving         = None
        else:
            comparison     = "none"
            cheaper_portal = None
            saving         = None

        games_out.append({
            "game_name":            name,
            "p1travel_url":         game["p1travel_url"],
            "champions_travel_url": game["champions_travel_url"],
            "p1_best":              p1_s.get("best"),
            "champs_best":          ch_s.get("best"),
            "comparison":           comparison,
            "cheaper_portal":       cheaper_portal,
            "saving":               saving,
        })

    # Write JSON
    output = {
        "last_updated":   datetime.now(timezone.utc).isoformat(),
        "threshold_low":  THRESHOLD_LOW,
        "threshold_high": THRESHOLD_HIGH,
        "games":          games_out,
        "failed_urls":    failed_out,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(output, indent=2))
    logger.info(f"Written → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
