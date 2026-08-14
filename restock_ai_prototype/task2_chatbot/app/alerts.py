"""
Feature 4 - Admin Demand Alerts.

Every chat turn about a product is logged to `chatbot_query_log`, and every
"notify me" lands in `customer_subscriptions`. Those two signals are combined
into a weighted demand score:

    demand_score = 1.0 * recent_queries + 3.0 * subscriptions

When an out-of-stock product crosses HIGH_INTEREST_THRESHOLD an entry is written
to `admin_demand_alerts` (the Admin Demand Log). If an alert is already open the
row is *updated* with the higher interest count rather than duplicated.
"""
from datetime import datetime, timedelta

from . import config, db


def log_query(product_id, query_type, query_text=""):
    """Record one chatbot interaction as a demand signal."""
    db.execute(
        """INSERT INTO chatbot_query_log (product_id, query_type, query_text)
           VALUES (%s, %s, %s)""",
        (product_id, query_type, (query_text or "")[:255]),
    )


def demand_score(product_id):
    """Weighted interest for a product inside the rolling interest window."""
    since = (datetime.now() - timedelta(days=config.INTEREST_WINDOW_DAYS)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    row = db.query(
        """SELECT
             (SELECT COUNT(*) FROM chatbot_query_log
               WHERE product_id = %s AND queried_at >= %s) AS query_count,
             (SELECT COUNT(*) FROM customer_subscriptions
               WHERE product_id = %s AND subscribed_at >= %s) AS sub_count""",
        (product_id, since, product_id, since),
        fetchone=True,
    )
    queries = int(row["query_count"] or 0)
    subs = int(row["sub_count"] or 0)
    score = queries * config.WEIGHT_QUERY + subs * config.WEIGHT_SUBSCRIPTION
    return {
        "queries": queries,
        "subscriptions": subs,
        "score": round(score, 1),
        "threshold": config.HIGH_INTEREST_THRESHOLD,
        "remaining": max(0, round(config.HIGH_INTEREST_THRESHOLD - score, 1)),
    }


def evaluate_product(product_id, reason="chat"):
    """
    Raise (or refresh) a high-interest alert if the product is out of stock and
    demand has crossed the threshold. Returns the alert dict, or None.
    """
    product = db.query(
        "SELECT * FROM products WHERE product_id = %s", (product_id,), fetchone=True
    )
    if not product or int(product["stock_level"]) > 0:
        return None

    signals = demand_score(product_id)
    if signals["score"] < config.HIGH_INTEREST_THRESHOLD:
        return None

    existing = db.query(
        """SELECT * FROM admin_demand_alerts
           WHERE product_id = %s AND alert_type = 'high_interest_oos' AND is_resolved = 0
           ORDER BY alert_id DESC""",
        (product_id,),
        fetchone=True,
    )

    message = (
        f"High demand on out-of-stock '{product['name']}': "
        f"{signals['queries']} chat queries + {signals['subscriptions']} restock "
        f"subscriptions (demand score {signals['score']}). Expedite the reorder."
    )

    if existing:
        if int(existing["interest_count"]) >= int(signals["score"]):
            return None  # nothing new to tell the admin
        db.execute(
            """UPDATE admin_demand_alerts
               SET interest_count = %s, alert_message = %s
               WHERE alert_id = %s""",
            (int(signals["score"]), message[:255], existing["alert_id"]),
        )
        return {
            "alert_id": existing["alert_id"],
            "product_id": product_id,
            "product_name": product["name"],
            "interest_count": int(signals["score"]),
            "alert_message": message,
            "is_new": False,
            "signals": signals,
        }

    alert_id, _ = db.execute(
        """INSERT INTO admin_demand_alerts
           (product_id, alert_type, interest_count, alert_message)
           VALUES (%s, 'high_interest_oos', %s, %s)""",
        (product_id, int(signals["score"]), message[:255]),
    )
    return {
        "alert_id": alert_id,
        "product_id": product_id,
        "product_name": product["name"],
        "interest_count": int(signals["score"]),
        "alert_message": message,
        "is_new": True,
        "reason": reason,
        "signals": signals,
    }


def open_alerts():
    """The Admin Demand Log feed, newest first."""
    rows = db.query(
        """SELECT a.alert_id, a.product_id, a.alert_type, a.interest_count,
                  a.alert_message, a.created_at, a.is_resolved,
                  p.name AS product_name, p.category, p.stock_level, p.price
           FROM admin_demand_alerts a
           JOIN products p ON p.product_id = a.product_id
           WHERE a.is_resolved = 0
           ORDER BY a.interest_count DESC, a.alert_id DESC"""
    )
    for row in rows:
        row["is_resolved"] = bool(row["is_resolved"])
    return rows


def resolve_for_product(product_id):
    """Called when stock lands — the demand alert is no longer actionable."""
    _, count = db.execute(
        """UPDATE admin_demand_alerts SET is_resolved = 1
           WHERE product_id = %s AND is_resolved = 0""",
        (product_id,),
    )
    return count


def demand_leaderboard(limit=8):
    """Out-of-stock products ranked by live demand score (drives the admin panel)."""
    products = db.query("SELECT * FROM products WHERE stock_level = 0 ORDER BY name")
    rows = []
    for product in products:
        signals = demand_score(product["product_id"])
        rows.append({
            "product_id": product["product_id"],
            "name": product["name"],
            "category": product["category"],
            "price": float(product["price"]),
            **signals,
            "alerting": signals["score"] >= config.HIGH_INTEREST_THRESHOLD,
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows[:limit]
