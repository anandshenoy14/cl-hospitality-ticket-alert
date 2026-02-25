"""
Reusable notification module — email via Resend API.
No SMTP credentials needed, just a RESEND_API_KEY env var.

Extensible: add Slack, webhooks, desktop notifications by
subclassing Notifier and implementing send().
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
    """Everything a notifier needs to deliver one alert."""
    subject: str
    html_body: str
    plain_body: str
    recipient: str
    metadata: dict | None = None


# ─── Base Interface ───────────────────────────────────────────────────────────

class Notifier(ABC):
    """Subclass this to add any notification channel."""

    @abstractmethod
    def send(self, payload: AlertPayload) -> bool:
        """Send alert. Returns True on success. Must never raise."""


# ─── Resend Email Notifier ────────────────────────────────────────────────────

class ResendEmailNotifier(Notifier):
    """
    Sends email via Resend's REST API.

    Required env var:  RESEND_API_KEY
    Optional env var:  RESEND_SENDER  (defaults to onboarding@resend.dev)

    The default sender works immediately on Resend's free plan with no
    domain setup. To use your own domain, verify it in the Resend dashboard
    and set RESEND_SENDER="Ticket Alert <alerts@yourdomain.com>".
    """

    def __init__(
        self,
        api_key: str | None = None,
        sender: str | None = None,
    ):
        self.api_key = api_key or os.environ["RESEND_API_KEY"]
        self.sender = sender or os.environ.get(
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


# ─── Extensibility stubs ──────────────────────────────────────────────────────

class SlackNotifier(Notifier):
    """Send to a Slack webhook — implement as needed."""
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, payload: AlertPayload) -> bool:
        try:
            r = requests.post(self.webhook_url, json={"text": payload.plain_body}, timeout=10)
            return r.ok
        except Exception as e:
            logger.error(f"Slack notify failed: {e}")
            return False


# ─── Alert Builder ────────────────────────────────────────────────────────────

def build_ticket_alert_payload(
    recipient: str,
    game_alerts: list[dict],
) -> AlertPayload:
    """
    Build a structured AlertPayload from a list of triggered games.
    Each game gets its own row in the email.
    """
    subject = f"🎟️ Ticket Price Alert – {len(game_alerts)} game(s) in range"

    rows_html = ""
    for g in game_alerts:
        prices_str = ", ".join(f"€{p:.0f}" for p in sorted(g["prices_in_range"]))
        rows_html += f"""
        <tr>
          <td style="padding:10px;border-bottom:1px solid #eee;font-weight:bold">{g['game_name']}</td>
          <td style="padding:10px;border-bottom:1px solid #eee;color:#27ae60">{prices_str}</td>
          <td style="padding:10px;border-bottom:1px solid #eee">€{g['threshold_low']} – €{g['threshold_high']}</td>
          <td style="padding:10px;border-bottom:1px solid #eee">
            <a href="{g['url']}" style="color:#2980b9">Buy Now</a>
          </td>
        </tr>"""

    html_body = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:700px;margin:auto">
      <h2 style="color:#2c3e50">🎟️ Ticket Price Alert</h2>
      <p>The following games have tickets <strong>within your price range</strong>:</p>
      <table width="100%" cellspacing="0" style="border-collapse:collapse">
        <thead>
          <tr style="background:#2c3e50;color:#fff">
            <th style="padding:10px;text-align:left">Game</th>
            <th style="padding:10px;text-align:left">Prices Found</th>
            <th style="padding:10px;text-align:left">Your Range</th>
            <th style="padding:10px;text-align:left">Link</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
      <p style="color:#7f8c8d;font-size:12px;margin-top:20px">
        Automated alert · max 10/day · 9 AM – 5 PM PST only
      </p>
    </body></html>"""

    lines = ["TICKET PRICE ALERT", "=" * 40]
    for g in game_alerts:
        prices_str = ", ".join(f"€{p:.0f}" for p in sorted(g["prices_in_range"]))
        lines += [
            f"\nGame:   {g['game_name']}",
            f"Prices: {prices_str}",
            f"Range:  €{g['threshold_low']} – €{g['threshold_high']}",
            f"Link:   {g['url']}",
        ]
    plain_body = "\n".join(lines)

    return AlertPayload(
        subject=subject,
        html_body=html_body,
        plain_body=plain_body,
        recipient=recipient,
        metadata={"game_count": len(game_alerts), "games": game_alerts},
    )
