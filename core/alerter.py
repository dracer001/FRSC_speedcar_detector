"""
core/alerter.py
────────────────
Stable, thread-safe email dispatch for the FRSC Speed Vigil system.

WHY THIS REPLACES THE OLD send_violation_report():
The old code sent one-shot mail through a personal Gmail account with an
app password and no timeout on the SMTP connection. That combination is
the classic cause of "sometimes it sends, sometimes it just hangs / dies
silently": Gmail can throttle or silently drop app-password logins, and
with no `timeout=` set, a stalled connection blocks the background thread
forever instead of failing fast.

This module instead uses the same pattern as the working IDS alerter:
  • A dedicated system mailbox (ids@yunivolt.com on mail.yunivolt.com)
    instead of a personal Gmail account.
  • An explicit socket timeout, so a bad connection fails fast.
  • A short retry loop (2 attempts w/ backoff) for transient network blips.
  • A single thread-safe class so both violation reports and test emails
    share the exact same, already-proven send path.
"""

import smtplib
import ssl
import time
import logging
import threading
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Tuple

log = logging.getLogger("frsc.alerter")

# ── System mailbox (the "ids email") ───────────────────────────────────────
# Matches the credentials already proven to work reliably. Override with
# env vars in production rather than editing these defaults.
DEFAULT_SMTP_HOST = "mail.yunivolt.com"
DEFAULT_SMTP_PORT = 465
DEFAULT_SENDER    = "ids@yunivolt.com"
DEFAULT_PASSWORD  = "Intrusion123!"   # override via SMTP_PASSWORD env var

ACCENT = "#f39c12"   # FRSC orange, matches the dashboard theme


class EmailAlerter:
    """Thread-safe, retrying SMTP sender for the FRSC Speed Vigil system."""

    def __init__(
        self,
        sender:      str = DEFAULT_SENDER,
        password:    str = DEFAULT_PASSWORD,
        smtp_host:   str = DEFAULT_SMTP_HOST,
        smtp_port:   int = DEFAULT_SMTP_PORT,
        timeout:     int = 15,
        max_retries: int = 2,
        retry_delay: int = 3,
        dry_run:     bool = False,
    ):
        self.sender      = sender
        self.password    = password
        self.smtp_host   = smtp_host
        self.smtp_port   = smtp_port
        self.timeout     = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.dry_run     = dry_run

        self._lock       = threading.Lock()
        self.sent_count   = 0
        self.failed_count = 0

    # ── low-level, retrying send ────────────────────────────────────────
    def _send(self, recipient: str, subject: str, text_body: str, html_body: str) -> Tuple[bool, str]:
        if not recipient:
            return False, "No recipient email configured"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"FRSC Speed Vigil <{self.sender}>"
        msg["To"]      = recipient
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        if self.dry_run:
            log.info(f"[DRY RUN] Would send: {subject} -> {recipient}")
            with self._lock:
                self.sent_count += 1
            return True, "sent (dry run)"

        last_err = "unknown error"
        for attempt in range(1, self.max_retries + 1):
            try:
                ctx = ssl.create_default_context()
                with smtplib.SMTP_SSL(
                    self.smtp_host, self.smtp_port, context=ctx, timeout=self.timeout
                ) as srv:
                    srv.login(self.sender, self.password)
                    srv.sendmail(self.sender, recipient, msg.as_string())
                with self._lock:
                    self.sent_count += 1
                log.info(f"[EMAIL] Sent to {recipient}: {subject}")
                return True, "sent"
            except Exception as e:
                last_err = str(e)
                log.warning(f"[EMAIL] Attempt {attempt}/{self.max_retries} failed: {last_err}")
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)

        with self._lock:
            self.failed_count += 1
        log.error(f"[EMAIL] Giving up after {self.max_retries} attempts: {last_err}")
        return False, last_err

    # ── shared HTML shell ───────────────────────────────────────────────
    def _wrap_html(self, heading: str, subtitle: str, rows: list, image_url: Optional[str] = None) -> str:
        rows_html = "".join(
            f"<tr><td style='padding:6px 14px;color:#8a94a3;font-size:12px;'>{k}</td>"
            f"<td style='padding:6px 14px;font-weight:600;font-size:13px;color:#e6e6e6;'>{v}</td></tr>"
            for k, v in rows
        )
        image_block = (
            f"<div style='margin-top:16px;'><img src='{image_url}' style='width:100%;"
            f"border-radius:8px;border:1px solid #232a35;' alt='Evidence'></div>"
            if image_url else ""
        )
        return f"""
<html><body style="margin:0;padding:0;background:#0b0e14;font-family:'Segoe UI',Tahoma,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:24px 16px;">
  <div style="background:#151921;border:1px solid #232a35;border-radius:12px;overflow:hidden;">
    <div style="background:{ACCENT};color:#000;padding:18px 22px;">
      <h2 style="margin:0;font-size:17px;letter-spacing:1px;">&#9889; {heading}</h2>
      <p style="margin:4px 0 0;font-size:12px;opacity:.75;">{subtitle}</p>
    </div>
    <div style="padding:20px 22px;">
      <table style="border-collapse:collapse;width:100%;background:#1c222d;border-radius:8px;overflow:hidden;">
        {rows_html}
      </table>
      {image_block}
      <p style="font-size:11px;color:#5a6472;margin-top:18px;">
        This message was generated automatically by the FRSC Speed Vigil system.
      </p>
    </div>
  </div>
</div>
</body></html>"""

    # ── public API ──────────────────────────────────────────────────────
    def send_violation_report(
        self,
        recipient:  str,
        image_url:  str,
        label:      str,
        confidence: float,
        location:   str,
        speed:      str,
        threshold:  str,
        system_id:  str = "SPEED-VIGIL-001",
    ) -> Tuple[bool, str]:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subject = f"[FRSC] Speed Violation Report — {location} — {ts}"

        rows = [
            ("Event Timestamp", ts),
            ("Location",        location),
            ("Classification",  label.upper()),
            ("Confidence",      f"{confidence:.1f}%"),
            ("Recorded Speed",  f"{speed} km/h"),
            ("Speed Threshold", f"{threshold} km/h"),
            ("System ID",       system_id),
        ]
        text_lines = [
            "OFFICIAL TRAFFIC RECORD",
            "-" * 45,
        ] + [f"{k:<18}: {v}" for k, v in rows] + [
            "-" * 45,
            f"Evidence Image  : {image_url}",
        ]
        text = "\n".join(text_lines)
        html = self._wrap_html(
            heading="Speed Violation Detected",
            subtitle=f"{system_id} &bull; {ts}",
            rows=rows,
            image_url=image_url,
        )
        return self._send(recipient, subject, text, html)

    def send_test(self, recipient: str) -> Tuple[bool, str]:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subject = "[FRSC] Test Alert — System Check"
        rows = [
            ("Time",       ts),
            ("SMTP Host",  f"{self.smtp_host}:{self.smtp_port}"),
            ("Sender",     self.sender),
            ("Note",       "This is a test email confirming delivery is working."),
        ]
        text = "FRSC SPEED VIGIL — TEST EMAIL\n" + "\n".join(f"{k:<12}: {v}" for k, v in rows)
        html = self._wrap_html(
            heading="Test Alert",
            subtitle="System Check &bull; " + ts,
            rows=rows,
        )
        return self._send(recipient, subject, text, html)
