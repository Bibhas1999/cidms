"""Sending email (password reset links for now). Sent after the response, so a slow mail server never
slows sign-in pages down, and how long a request takes never reveals whether an email address exists."""

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings

log = logging.getLogger("app.mail")


def send(to: str, subject: str, body: str) -> None:
    s = get_settings()
    if not s.smtp_host:
        if s.is_production:
            log.error("Email isn't set up (SMTP_HOST); couldn't send %r", subject)
        else:
            # Development without email: the message goes to the log, so the link can still be used.
            log.info("Email to %s: %s\n%s", to, subject, body)
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.mail_from, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if s.smtp_username:
                smtp.login(s.smtp_username, s.smtp_password)
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException):
        log.exception("Couldn't send email %r", subject)
