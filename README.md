# 🎟️ CL Hospitality Ticket Alert

An automated ticket price monitoring service for UEFA Champions League games. It scrapes live ticket prices from hospitality travel websites and sends email alerts when prices fall within your target range — running entirely free via GitHub Actions and Resend.

---

## What It Does

Every hour between **9 AM and 5 PM PST**, the service:

1. Visits each configured ticket page using a real headless browser (Playwright + Chromium)
2. Waits for the page to fully load including all JavaScript-rendered prices
3. Extracts every EUR-priced ticket found on the page
4. Checks if any price falls within your target range (€100 – €500)
5. Sends a formatted email alert listing each game, its in-range prices, and a direct buy link
6. Caps itself at **10 alerts per day** to avoid inbox flooding

Your Mac can be off, asleep, or closed the entire time — GitHub's servers do all the work.

---

## How It Works

```
GitHub Cron (every hour, 9AM–5PM PST)
           │
           ▼
     run_once.py
     ┌─────────────────────────────────────┐
     │  1. Check alert window (9AM–5PM)    │
     │  2. Check daily cap (max 10/day)    │
     │  3. Scrape all game URLs            │
     │     └── scraper.py (Playwright)     │
     │  4. Filter prices in €100–€500      │
     │  5. Send alert email                │
     │     └── notifier.py (Resend API)    │
     └─────────────────────────────────────┘
```

### The Files

| File | What it does |
|---|---|
| `.github/workflows/ticket_alert.yml` | Tells GitHub when to run the service (the cron schedule) |
| `run_once.py` | The main script — orchestrates scraping, filtering, and alerting |
| `scraper.py` | Launches a headless Chromium browser, loads each ticket page, and extracts EUR prices |
| `notifier.py` | Sends the alert email via the Resend API. Built as a reusable module — easy to extend to Slack, SMS, etc. |
| `requirements.txt` | Python dependencies (Playwright and Requests) |

---

## Games Currently Monitored

| Club | URL |
|---|---|
| Arsenal vs TBC | https://www.p1travel.com/en/football/champions-league/arsenal-vs-tbc-date-tbc |
| Manchester City vs TBC | https://www.p1travel.com/en/football/champions-league/manchester-city-vs-tbc-date-tbc |
| Chelsea vs TBC | https://champions-travel.com/tickets/uefa-champions-league?chelsea-v-tbc |

---

## Alert Settings

| Setting | Current value | Where to change it |
|---|---|---|
| Price range | €100 – €500 | `run_once.py` → `THRESHOLD_LOW` / `THRESHOLD_HIGH` |
| Alert window | 9 AM – 5 PM PST | `run_once.py` → `ALERT_WINDOW_START` / `ALERT_WINDOW_END` |
| Timezone | PST (Los Angeles) | `run_once.py` → `TIMEZONE` |
| Max alerts/day | 10 | `run_once.py` → `MAX_ALERTS_PER_DAY` |
| Recipient email | anandshenoyuidev@gmail.com | `run_once.py` → `RECIPIENT_EMAIL` |
| Poll frequency | Every hour | `.github/workflows/ticket_alert.yml` → `cron` lines |

---

## How to Add More Games

Open `run_once.py` and find the `GAMES` list near the top. Add a new entry following the same pattern:

```python
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

    # ✅ Add new games here — copy the block below and update name and url
    {
        "name": "Liverpool vs TBC (Champions League)",
        "url": "https://www.p1travel.com/en/football/champions-league/liverpool-vs-tbc-date-tbc",
    },
]
```

Any URL from P1 Travel or Champions Travel works. Each game gets its own row in the alert email with its own prices and buy link. All games are scraped in parallel so adding more does not slow things down.

---

## How to Change the Price Range

Open `run_once.py` and update these two lines:

```python
THRESHOLD_LOW  = 100   # € minimum — change this
THRESHOLD_HIGH = 500   # € maximum — change this
```

For example, to only alert on tickets under €200:

```python
THRESHOLD_LOW  = 50
THRESHOLD_HIGH = 200
```

---

## How to Add More Alert Recipients

Open `notifier.py` and find the `send()` method inside `ResendEmailNotifier`. The Resend API accepts a list of addresses — update the `to` field:

```python
"to": ["person1@gmail.com", "person2@gmail.com"],
```

---

## Infrastructure & Cost

| Component | Service | Cost |
|---|---|---|
| Compute (runs the scraper) | GitHub Actions | Free — ~248 min/month of 2,000 free |
| Email delivery | Resend | Free — ~300 emails/month of 3,000 free |
| Secrets storage | GitHub Secrets | Free |
| **Total** | | **$0 / month** |

---

## Secrets Required

One secret must be set in **GitHub repo → Settings → Secrets and variables → Actions → New repository secret**:

| Secret name | Value |
|---|---|
| `RESEND_API_KEY` | Your Resend API key from [resend.com](https://resend.com) |

---

## Running a Manual Test

Go to your GitHub repo → **Actions** tab → **CL Hospitality Ticket Alert** → **Run workflow** → **Run workflow**.

This triggers an immediate run outside the cron schedule. Check the logs to confirm prices are being found and emails are sending correctly.
