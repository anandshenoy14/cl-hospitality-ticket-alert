# 🎟️ CL Hospitality Ticket Alert

A personal Champions League hospitality ticket price tracker. GitHub Actions scrapes two ticket portals every hour and writes the results to a JSON file. A PWA (Progressive Web App) hosted on GitHub Pages reads that file and displays live prices — installable on iPhone and Android like a native app, no App Store required.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     GitHub Actions                          │
│                                                             │
│  Cron: every hour, 9AM–5PM PST                              │
│                    │                                        │
│                    ▼                                        │
│             run_once.py                                     │
│                    │                                        │
│       ┌────────────┴────────────┐                           │
│       ▼                         ▼                           │
│  scraper.py                scraper.py                       │
│  (P1 Travel URLs)          (Champions Travel URLs)          │
│  Playwright + Chromium     Playwright + Chromium            │
│  checks robots.txt first   checks robots.txt first          │
│       │                         │                           │
│       └────────────┬────────────┘                           │
│                    ▼                                        │
│          docs/data/prices.json                              │
│          (committed back to repo)                           │
└─────────────────────────────────────────────────────────────┘
                      │
                      │  GitHub Pages serves docs/ folder
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                   GitHub Pages (free)                       │
│                                                             │
│   https://YOUR_USERNAME.github.io/cl-hospitality-ticket-alert/  │
│                                                             │
│   docs/index.html    ← PWA shell                           │
│   docs/manifest.json ← makes it installable                │
│   docs/sw.js         ← service worker (offline support)    │
│   docs/data/prices.json ← updated every hour by Actions    │
└─────────────────────────────────────────────────────────────┘
                      │
                      │  fetches prices.json on open/foreground
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              PWA on your phone                              │
│                                                             │
│   iPhone  → Safari → Share → Add to Home Screen            │
│   Android → Chrome → Menu → Install App                    │
│                                                             │
│   - Auto-refreshes when opened or switched to foreground   │
│   - Works offline using last known prices                  │
│   - Shows portal comparison per game                       │
│   - Highlights cheaper portal in green                     │
│   - Reports failed URLs in red                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Scraping load (legal compliance)

| Metric | Value |
|---|---|
| Games monitored | 3 |
| Portals per game | 2 (P1 Travel + Champions Travel) |
| Page loads per scrape | 6 |
| Scrapes per day | 9 (one per hour, 9AM–5PM PST) |
| **Total page loads/day** | **54** |
| Frequency per URL | Once per hour — equivalent to a normal user |
| robots.txt | Checked before every scrape |
| User-Agent | Honest, identifies the bot with contact email |
| Data use | Personal only, not commercial |

---

## Files

```
cl-hospitality-ticket-alert/
├── .github/
│   └── workflows/
│       └── ticket_alert.yml   ← cron schedule + commits prices.json
├── docs/                       ← served by GitHub Pages
│   ├── index.html              ← PWA app (the thing you install on your phone)
│   ├── manifest.json           ← makes it installable as an app
│   ├── sw.js                   ← service worker for offline support
│   ├── icons/
│   │   ├── icon-192.png        ← app icon
│   │   └── icon-512.png        ← app icon
│   └── data/
│       └── prices.json         ← written by GitHub Actions each run
├── scraper.py                  ← Playwright headless browser scraper
├── run_once.py                 ← orchestrates scraping, writes prices.json
└── requirements.txt            ← Python deps (playwright, requests)
```

---

## Games monitored

| Club | P1 Travel URL | Champions Travel URL |
|---|---|---|
| Arsenal vs TBC | p1travel.com/…/arsenal-vs-tbc | champions-travel.com/…?arsenal-v-tbc |
| Manchester City vs TBC | p1travel.com/…/manchester-city-vs-tbc | champions-travel.com/…?manchester-city-v-tbc |
| Chelsea vs TBC | p1travel.com/…/chelsea-vs-tbc | champions-travel.com/…?chelsea-v-tbc |

---

## What the PWA shows

Each game card has three states:

| State | Badge | Meaning |
|---|---|---|
| Both portals in range | 🟢 Both portals | Both have prices in €100–€500. Cheaper one highlighted in green. |
| One portal in range | 🟡 P1 only / CT only | Only one portal has in-range prices. Shown in blue. |
| Neither in range | ⚪ No prices | Both portals loaded but no prices in range. |
| URL failed | 🔴 Failed URLs section | Portal errored or returned no prices at all. |

---

## How to add more games

Open `run_once.py` and add a new entry to the `GAMES` list:

```python
{
    "name": "Liverpool vs TBC",
    "p1travel_url": "https://www.p1travel.com/en/football/champions-league/liverpool-vs-tbc-date-tbc",
    "champions_travel_url": "https://champions-travel.com/tickets/uefa-champions-league?liverpool-v-tbc",
},
```

Each new game adds 2 more page loads per scrape (18 loads/day for a 4th game, for example). Still well within ethical scraping limits.

---

## How to change the price range

In `run_once.py`:

```python
THRESHOLD_LOW  = 100   # € minimum
THRESHOLD_HIGH = 500   # € maximum
```

---

## Setup

### 1. Create GitHub repo
Go to [github.com/new](https://github.com/new) → name it `cl-hospitality-ticket-alert` → Private → Create.

### 2. Upload all files
Upload every file maintaining the folder structure above. For `.github/workflows/ticket_alert.yml`, type the full path in the GitHub file name box — GitHub creates the folders automatically.

### 3. Enable GitHub Pages
**Settings → Pages → Source → Deploy from branch**
- Branch: `main`
- Folder: `/docs`
- Save

Your app will be live at:
```
https://YOUR_USERNAME.github.io/cl-hospitality-ticket-alert/
```

### 4. Trigger a manual test
**Actions → CL Hospitality Ticket Alert → Run workflow → Run workflow**

This runs immediately and commits updated `prices.json` to the repo. Open your GitHub Pages URL after it finishes to see prices.

### 5. Install on phone

**iPhone:** Open the URL in Safari → tap **Share ↑** → **Add to Home Screen** → **Add**

**Android:** Open in Chrome → tap **⋮** → **Install app**

---

## How multiple users work

The ticket sites are never contacted by users directly. Every user's phone fetches `prices.json` from GitHub's CDN — a file GitHub is already serving. The scraping load on ticket portals is fixed at 54 page loads/day regardless of how many people use the PWA.

---

## Infrastructure cost

| Component | Service | Cost |
|---|---|---|
| Scraping compute | GitHub Actions | Free — ~54 min/month of 2,000 free |
| PWA hosting | GitHub Pages | Free — 100GB/month bandwidth |
| Data file | GitHub repo | Free |
| **Total** | | **$0 / month** |
