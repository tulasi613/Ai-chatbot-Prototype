"""
Feature 3 - Customer subscription capture (straight from the chat window).

Handles validation, de-duplication, persistence to `customer_subscriptions`,
and the restock notification sweep the admin triggers.
"""
import re

from . import alerts, db

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(?:\+?\d[\d\-\s().]{7,17}\d)")


def extract_contact(text):
    """Pull an email and/or phone number out of a free-text chat message."""
    email_match = EMAIL_RE.search(text or "")
    email = email_match.group(0) if email_match else None

    phone = None
    remainder = (text or "").replace(email or "", " ")
    phone_match = PHONE_RE.search(remainder)
    if phone_match:
        candidate = phone_match.group(0).strip()
        if len(re.sub(r"\D", "", candidate)) >= 8:
            phone = candidate
    return email, phone


def validate(email, phone):
    """Returns (ok, error_message)."""
    if not email and not phone:
        return False, "I need either an email address or a phone number to notify you."
    if email and not EMAIL_RE.fullmatch(email.strip()):
        return False, f"'{email}' doesn't look like a valid email address."
    if phone and len(re.sub(r"\D", "", phone)) < 8:
        return False, f"'{phone}' doesn't look like a valid phone number."
    return True, None


def subscribe(product_id, email=None, phone=None):
    """
    Save a restock subscription. Returns
    (result_dict, error_message) - exactly one of them is None.
    """
    email = (email or "").strip() or None
    phone = (phone or "").strip() or None

    ok, error = validate(email, phone)
    if not ok:
        return None, error

    product = db.query(
        "SELECT * FROM products WHERE product_id = %s", (product_id,), fetchone=True
    )
    if not product:
        return None, "I couldn't find that product."

    existing = db.query(
        """SELECT * FROM customer_subscriptions
           WHERE product_id = %s AND notified = 0
             AND ((customer_email IS NOT NULL AND customer_email = %s)
                  OR (customer_phone IS NOT NULL AND customer_phone = %s))""",
        (product_id, email, phone),
        fetchone=True,
    )
    if existing:
        return {
            "subscription_id": existing["subscription_id"],
            "product_id": product_id,
            "product_name": product["name"],
            "email": existing["customer_email"],
            "phone": existing["customer_phone"],
            "duplicate": True,
            "admin_alert": None,
            "total_waiting": count_waiting(product_id),
        }, None

    sub_id, _ = db.execute(
        """INSERT INTO customer_subscriptions (product_id, customer_email, customer_phone)
           VALUES (%s, %s, %s)""",
        (product_id, email, phone),
    )

    # A subscription is the strongest interest signal we have -> re-check demand.
    alert = alerts.evaluate_product(product_id, reason="subscription")

    return {
        "subscription_id": sub_id,
        "product_id": product_id,
        "product_name": product["name"],
        "email": email,
        "phone": phone,
        "duplicate": False,
        "admin_alert": alert,
        "total_waiting": count_waiting(product_id),
    }, None


def count_waiting(product_id):
    row = db.query(
        """SELECT COUNT(*) AS n FROM customer_subscriptions
           WHERE product_id = %s AND notified = 0""",
        (product_id,),
        fetchone=True,
    )
    return int(row["n"] or 0)


def list_subscriptions(limit=25):
    rows = db.query(
        """SELECT s.subscription_id, s.product_id, s.customer_email, s.customer_phone,
                  s.subscribed_at, s.notified, s.notified_at,
                  p.name AS product_name, p.stock_level
           FROM customer_subscriptions s
           JOIN products p ON p.product_id = s.product_id
           ORDER BY s.subscription_id DESC
           LIMIT %s""",
        (limit,),
    )
    for row in rows:
        row["notified"] = bool(row["notified"])
    return rows


def notify_waiting(product_id, new_stock_level):
    """
    Restock sweep: mark everyone waiting on this product as notified and return
    the (simulated) messages so the UI can show them.
    """
    product = db.query(
        "SELECT * FROM products WHERE product_id = %s", (product_id,), fetchone=True
    )
    waiting = db.query(
        """SELECT * FROM customer_subscriptions
           WHERE product_id = %s AND notified = 0""",
        (product_id,),
    )

    messages = []
    for sub in waiting:
        channel = "email" if sub["customer_email"] else "sms"
        target = sub["customer_email"] or sub["customer_phone"]
        db.execute(
            """UPDATE customer_subscriptions
               SET notified = 1, notified_at = NOW()
               WHERE subscription_id = %s""",
            (sub["subscription_id"],),
        )
        messages.append({
            "channel": channel,
            "to": target,
            "body": f"Good news — {product['name']} is back in stock "
                    f"({new_stock_level} available). Order now before it sells out again.",
        })
    return messages
