"""
Sends restock notifications to subscribed customers.

Behavior:
  - If SENDGRID_API_KEY is set  -> sends via SendGrid.
  - Elif SMTP_HOST/USER/PASSWORD are set -> sends via SMTP.
  - Else -> SIMULATED mode: prints the notification and appends it to
    notifications_log.json so the prototype is fully demo-able without
    any real credentials configured.
"""
import json
import os
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

from config import SMTP_CONFIG, SENDGRID_API_KEY

LOG_PATH = os.path.join(os.path.dirname(__file__), "notifications_log.json")


def _append_log(entry):
    log = []
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, "r") as f:
                log = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            log = []
    log.append(entry)
    with open(LOG_PATH, "w") as f:
        json.dump(log, f, indent=2, default=str)


def _send_via_sendgrid(to_email, subject, body):
    import requests  # local import so it's optional
    resp = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={
            "Authorization": f"Bearer {SENDGRID_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": SMTP_CONFIG["from_email"]},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}],
        },
        timeout=10,
    )
    return resp.status_code in (200, 201, 202)


def _send_via_smtp(to_email, subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_CONFIG["from_email"]
    msg["To"] = to_email

    with smtplib.SMTP(SMTP_CONFIG["host"], SMTP_CONFIG["port"]) as server:
        server.starttls()
        server.login(SMTP_CONFIG["user"], SMTP_CONFIG["password"])
        server.sendmail(SMTP_CONFIG["from_email"], [to_email], msg.as_string())
    return True


def send_restock_notification(customer_email, customer_phone, product_name, new_stock_level):
    subject = f"Back in stock: {product_name}"
    body = (
        f"Good news! \"{product_name}\" is back in stock "
        f"({new_stock_level} units available). "
        f"Order now before it sells out again."
    )

    mode = "simulated"
    success = True
    try:
        if SENDGRID_API_KEY and customer_email:
            success = _send_via_sendgrid(customer_email, subject, body)
            mode = "sendgrid"
        elif SMTP_CONFIG["host"] and SMTP_CONFIG["user"] and customer_email:
            success = _send_via_smtp(customer_email, subject, body)
            mode = "smtp"
        else:
            # SIMULATED notification (default for the prototype)
            print(f"[SIMULATED NOTIFICATION] -> {customer_email or customer_phone}: {subject}")
            mode = "simulated"
    except Exception as e:
        success = False
        print(f"[NOTIFICATION ERROR] {e}")

    entry = {
        "timestamp": datetime.now().isoformat(),
        "channel": mode,
        "to_email": customer_email,
        "to_phone": customer_phone,
        "product_name": product_name,
        "new_stock_level": new_stock_level,
        "subject": subject,
        "body": body,
        "success": success,
    }
    _append_log(entry)
    return success
