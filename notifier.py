"""
Reusable notification module — email via Resend API.
Extensible: subclass Notifier to add Slack, SMS, webhooks etc.

Note on Resend free tier: emails can only be sent to the address you
signed up with unless you verify a custom domain at resend.com/domains.
"""

import os
import logging
import requests
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


# ─── Data Contract ────────────────────────────────────────────────────────────

@dataclass
class AlertPayload:
    subject: str
    html_body: str
    plain_body: str
    recipient: str
    metadata: dict | None = None


# ─── Base Interface ───────────────────────────────────────────────────────────

class Notifier(ABC):
    @abstractmethod
    def send(self, payload: AlertPayload) -> bool:
        """Send alert. Returns True on success. Must never raise."""


# ─── Resend Email Notifier ────────────────────────────────────────────────────

class ResendEmailNotifier(Notifier):
    def __init__(self, api_key: str | None = None, sender: str | None = None):
        self.api_key = api_key or os.environ["RESEND_API_KEY"]
        self.sender  = sender or os.environ.get(
            "RESEND_SENDER", "Ticket Alert <onboarding@resend.dev>"
        )

    def send(self, payload: AlertPayload) -> bool:
        try:
            response = requests.post(
                RESEND_API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": self.sender,
                    "to": [payload.recipient],
                    "subject": payload.subject,
                    "html": payload.html_body,
                    "text": payload.plain_body,
                },
                timeout=10,
            )
            response.raise_for_status()
            email_id = response.json().get("id", "unknown")
            logger.info(f"Email sent via Resend (id={email_id}) to {payload.recipient}")
            return True
        except requests.exceptions.HTTPError as e:
            logger.error(f"Resend API error {e.response.status_code}: {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"Resend send failed: {e}")
            return False


# ─── Alert Builder ────────────────────────────────────────────────────────────

def build_ticket_alert_payload(
    recipient: str,
    game_alerts: list[dict],
    failed_urls: list[dict],
    threshold_low: int,
    threshold_high: int,
) -> AlertPayload:
    """
    Builds the alert email with two sections:
    1. Price comparison table — games where both portals are in range
    2. Failed URLs section — portals that errored or returned no prices
    """
    has_alerts  = bool(game_alerts)
    has_failures = bool(failed_urls)

    # ── Subject ───────────────────────────────────────────────────────────────
    parts = []
    if has_alerts:
        parts.append(f"{len(game_alerts)} game(s) in range")
    if has_failures:
        parts.append(f"{len(failed_urls)} URL(s) failed")
    subject = "🎟️ Ticket Alert — " + " · ".join(parts)

    # ── HTML: price comparison table ──────────────────────────────────────────
    alerts_html = ""
    if has_alerts:
        rows_html = ""
        for g in game_alerts:
            p1_is_cheaper = g["cheaper_portal"] == "P1 Travel"
            p1_style      = "color:#27ae60;font-weight:bold" if p1_is_cheaper     else "color:#555"
            champs_style  = "color:#27ae60;font-weight:bold" if not p1_is_cheaper else "color:#555"
            verdict       = f"✅ {g['cheaper_portal']} cheaper by €{g['saving']:.0f}"

            rows_html += f"""
            <tr style="border-bottom:1px solid #eee">
              <td style="padding:14px 10px;font-weight:bold;vertical-align:top">{g['game_name']}</td>
              <td style="padding:14px 10px;vertical-align:top">
                <span style="{p1_style}">€{g['p1_best']:.0f}</span><br>
                <a href="{g['p1travel_url']}" style="font-size:11px;color:#2980b9">P1 Travel →</a>
              </td>
              <td style="padding:14px 10px;vertical-align:top">
                <span style="{champs_style}">€{g['champs_best']:.0f}</span><br>
                <a href="{g['champions_travel_url']}" style="font-size:11px;color:#2980b9">Champions Travel →</a>
              </td>
              <td style="padding:14px 10px;vertical-align:top;color:#27ae60;font-size:13px">{verdict}</td>
            </tr>"""

        alerts_html = f"""
        <h3 style="color:#2c3e50;margin-top:0">🟢 Prices in range on both portals</h3>
        <p style="color:#555;margin-top:-8px">Both portals have tickets within €{threshold_low}–€{threshold_high}. Cheaper option highlighted in green.</p>
        <table width="100%" cellspacing="0" style="border-collapse:collapse;margin-bottom:32px">
          <thead>
            <tr style="background:#2c3e50;color:#fff;text-align:left">
              <th style="padding:12px 10px">Game</th>
              <th style="padding:12px 10px">P1 Travel</th>
              <th style="padding:12px 10px">Champions Travel</th>
              <th style="padding:12px 10px">Verdict</th>
            </tr>
          </thead>
          <tbody>{rows_html}</tbody>
        </table>"""

    # ── HTML: failed URLs section ─────────────────────────────────────────────
    failures_html = ""
    if has_failures:
        failure_rows = ""
        for f in failed_urls:
            failure_rows += f"""
            <tr style="border-bottom:1px solid #fde">
              <td style="padding:12px 10px;font-weight:bold">{f['game_name']}</td>
              <td style="padding:12px 10px;color:#c0392b">{f['portal']}</td>
              <td style="padding:12px 10px">
                <a href="{f['url']}" style="color:#2980b9;font-size:12px">{f['url']}</a>
              </td>
              <td style="padding:12px 10px;color:#888;font-size:12px">{f['reason']}</td>
            </tr>"""

        failures_html = f"""
        <h3 style="color:#c0392b">🔴 URLs that could not be checked</h3>
        <p style="color:#555;margin-top:-8px">These pages failed to load or returned no prices. Check the links manually.</p>
        <table width="100%" cellspacing="0" style="border-collapse:collapse">
          <thead>
            <tr style="background:#c0392b;color:#fff;text-align:left">
              <th style="padding:10px">Game</th>
              <th style="padding:10px">Portal</th>
              <th style="padding:10px">URL</th>
              <th style="padding:10px">Reason</th>
            </tr>
          </thead>
          <tbody>{failure_rows}</tbody>
        </table>"""

    html_body = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:800px;margin:auto;color:#2c3e50">
      <h2 style="color:#2c3e50">🎟️ CL Hospitality Ticket Alert</h2>
      {alerts_html}
      {failures_html}
      <p style="color:#aaa;font-size:11px;margin-top:32px">
        Automated alert · max 10/day · 9 AM – 5 PM PST only.
      </p>
    </body></html>"""

    # ── Plain text ────────────────────────────────────────────────────────────
    lines = ["CL HOSPITALITY TICKET ALERT", "=" * 50, ""]

    if has_alerts:
        lines.append(f"PRICES IN RANGE (€{threshold_low}–€{threshold_high}) ON BOTH PORTALS")
        lines.append("-" * 50)
        for g in game_alerts:
            lines += [
                f"Game:              {g['game_name']}",
                f"P1 Travel:         €{g['p1_best']:.0f}  →  {g['p1travel_url']}",
                f"Champions Travel:  €{g['champs_best']:.0f}  →  {g['champions_travel_url']}",
                f"Verdict:           {g['cheaper_portal']} is cheaper by €{g['saving']:.0f}",
                "",
            ]

    if has_failures:
        lines.append("FAILED URLS — CHECK MANUALLY")
        lines.append("-" * 50)
        for f in failed_urls:
            lines += [
                f"Game:    {f['game_name']}",
                f"Portal:  {f['portal']}",
                f"URL:     {f['url']}",
                f"Reason:  {f['reason']}",
                "",
            ]

    plain_body = "\n".join(lines)

    return AlertPayload(
        subject=subject,
        html_body=html_body,
        plain_body=plain_body,
        recipient=recipient,
        metadata={
            "game_alerts": len(game_alerts),
            "failed_urls": len(failed_urls),
        },
    )
