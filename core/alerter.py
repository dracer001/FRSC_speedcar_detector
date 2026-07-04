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

NOTE ON SPAM FILTERING:
An earlier version of this email used a bright color banner, emoji in the
subject/body, and no Date/Message-ID headers — the receiving SMTP server
rejected it outright as "high-probability spam" (550). Marketing-style
HTML (big colored blocks, emoji, decorative bullets) reads exactly like a
spam template to content filters, and missing standard headers is itself
a red flag. The email below is deliberately plain: a simple bordered box,
black text on white, no emoji, no bright backgrounds, and proper
Date/Message-ID headers — the same shape as a normal transactional email.
"""

import smtplib
import ssl
import time
import logging
import threading
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from typing import Optional, Tuple

log = logging.getLogger("frsc.alerter")

# ── System mailbox (the "ids email") ───────────────────────────────────────
# Matches the credentials already proven to work reliably. Override with
# env vars in production rather than editing these defaults.
DEFAULT_SMTP_HOST = "mail.yunivolt.com"
DEFAULT_SMTP_PORT = 465
DEFAULT_SENDER    = "ids@yunivolt.com"
DEFAULT_PASSWORD  = "Intrusion123!"   # override via SMTP_PASSWORD env var


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

        self._lock        = threading.Lock()
        self.sent_count   = 0
        self.failed_count = 0

    # ── low-level, retrying send ────────────────────────────────────────
    def _send(self, recipient: str, subject: str, text_body: str, html_body: str) -> Tuple[bool, str]:
        if not recipient:
            return False, "No recipient email configured"

        domain = self.sender.split("@")[-1] if "@" in self.sender else "yunivolt.com"

        msg = MIMEMultipart("alternative")
        msg["Subject"]    = subject
        msg["From"]       = f"FRSC Speed Vigil <{self.sender}>"
        msg["To"]         = recipient
        msg["Date"]       = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=domain)
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

    # ── shared HTML shell — plain, no marketing-style styling ───────────
    def _wrap_html(self, heading: str, rows: list, image_url: Optional[str] = None) -> str:
        rows_html = "".join(
            f"<tr>"
            f"<td style='padding:4px 10px 4px 0;color:#555555;font-size:13px;white-space:nowrap;'>{k}</td>"
            f"<td style='padding:4px 0;color:#111111;font-size:13px;'>{v}</td>"
            f"</tr>"
            for k, v in rows
        )
        image_block = (
            f"<p style='margin:16px 0 0;'><a href='{image_url}'>View evidence image</a></p>"
            if image_url else ""
        )
        return f"""<html><body style="margin:0;padding:0;background:#ffffff;font-family:Arial,Helvetica,sans-serif;color:#111111;">
<div style="max-width:520px;margin:0 auto;padding:20px;">
  <p style="font-size:14px;margin:0 0 4px;font-weight:bold;">{heading}</p>
  <hr style="border:none;border-top:1px solid #dddddd;margin:8px 0 16px;">
  <table style="border-collapse:collapse;">
    {rows_html}
  </table>
  {image_block}
  <p style="font-size:11px;color:#888888;margin-top:20px;">
    Automated message from the FRSC Speed Vigil system.
  </p>
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
        subject = f"FRSC Speed Vigil - Violation at {location}"

        rows = [
            ("Time",       ts),
            ("Location",   location),
            ("Detected",   label),
            ("Confidence", f"{confidence:.1f}%"),
            ("Speed",      f"{speed} km/h"),
            ("Threshold",  f"{threshold} km/h"),
            ("System ID",  system_id),
        ]
        text_lines = [
            "FRSC Speed Vigil - Violation Report",
            "",
        ] + [f"{k}: {v}" for k, v in rows] + [
            "",
            f"Evidence image: {image_url}",
        ]
        text = "\n".join(text_lines)
        html = self._wrap_html(
            heading="FRSC Speed Vigil - Violation Report",
            rows=rows,
            image_url=image_url,
        )
        return self._send(recipient, subject, text, html)

    def send_test(self, recipient: str) -> Tuple[bool, str]:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subject = "FRSC Speed Vigil - Test Email"
        rows = [
            ("Time",   ts),
            ("Server", f"{self.smtp_host}"),
            ("Sender", self.sender),
        ]
        text = (
            "This is a test email from the FRSC Speed Vigil system.\n\n"
            + "\n".join(f"{k}: {v}" for k, v in rows)
            + "\n\nIf you received this, email delivery is working correctly."
        )
        html = self._wrap_html(
            heading="FRSC Speed Vigil - Test Email",
            rows=rows + [("Note", "If you received this, email delivery is working correctly.")],
        )
        return self._send(recipient, subject, text, html)
