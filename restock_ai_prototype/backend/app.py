"""
Smart Restock AI - Backend API (Flask)

CORE TASK 2 ENDPOINTS (the 3 required chatbot endpoints):
  1. POST /api/chat/availability   -> predict restock ETA for an OOS product
  2. POST /api/chat/alternatives   -> suggest 2-3 in-stock alternatives
  3. POST /api/chat/subscribe      -> save a customer's restock subscription
                                       (also fires the Admin Demand Alert)

SUPPORTING ENDPOINTS (used by the chatbot UI / admin dashboard):
  GET  /api/products               -> list/search products (for the chatbot's
                                       "find a product" step before Task 2 runs)
  GET  /api/products/<id>
  GET  /api/admin/alerts           -> admin demand alert feed
  POST /api/admin/restock          -> Task 4: admin updates stock -> triggers
                                       the customer notification loop
"""
from flask import Flask, request, jsonify
from flask_cors import CORS

import db
import predictor
import notifier
from config import HIGH_INTEREST_THRESHOLD

app = Flask(__name__)
CORS(app)  # allow the static chatbot_ui/index.html (different origin) to call this API


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _get_product_or_404(product_id):
    product = db.query(
        "SELECT * FROM products WHERE product_id = %s", (product_id,), fetchone=True
    )
    return product


def _log_chatbot_query(product_id, query_type, query_text=""):
    db.execute(
        """INSERT INTO chatbot_query_log (product_id, query_type, query_text)
           VALUES (%s, %s, %s)""",
        (product_id, query_type, query_text),
    )


def _maybe_raise_admin_demand_alert(product_id):
    """
    Task 2 - Admin Demand Alert:
    If combined interest (chatbot queries + active subscriptions) for an
    out-of-stock product crosses HIGH_INTEREST_THRESHOLD, and there isn't
    already an unresolved alert for it, insert one into admin_demand_alerts.
    """
    counts = db.query(
        """SELECT
             (SELECT COUNT(*) FROM chatbot_query_log WHERE product_id = %s) AS query_count,
             (SELECT COUNT(*) FROM customer_subscriptions WHERE product_id = %s) AS sub_count
        """,
        (product_id, product_id),
        fetchone=True,
    )
    interest_count = counts["query_count"] + counts["sub_count"]

    if interest_count < HIGH_INTEREST_THRESHOLD:
        return None

    existing = db.query(
        """SELECT * FROM admin_demand_alerts
           WHERE product_id = %s AND alert_type = 'high_interest_oos' AND is_resolved = FALSE""",
        (product_id,),
        fetchone=True,
    )
    if existing:
        return None  # already alerted, don't spam

    product = _get_product_or_404(product_id)
    message = (
        f"High customer interest detected for out-of-stock item "
        f"'{product['name']}' ({interest_count} signals: queries + subscriptions). "
        f"Consider expediting reorder."
    )
    alert_id, _ = db.execute(
        """INSERT INTO admin_demand_alerts (product_id, alert_type, interest_count, alert_message)
           VALUES (%s, 'high_interest_oos', %s, %s)""",
        (product_id, interest_count, message),
    )
    return {"alert_id": alert_id, "message": message, "interest_count": interest_count}


# ------------------------------------------------------------------
# Product lookup / search (supports the chatbot before it calls the
# 3 core endpoints below)
# ------------------------------------------------------------------
@app.route("/api/products", methods=["GET"])
def list_products():
    search = request.args.get("q", "").strip()
    if search:
        rows = db.query(
            "SELECT * FROM products WHERE name LIKE %s ORDER BY name LIMIT 20",
            (f"%{search}%",),
        )
    else:
        rows = db.query("SELECT * FROM products ORDER BY name LIMIT 50")
    return jsonify(rows)


@app.route("/api/products/<int:product_id>", methods=["GET"])
def get_product(product_id):
    product = _get_product_or_404(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404
    return jsonify(product)


# ------------------------------------------------------------------
# TASK 2 - ENDPOINT 1: Predict Availability
# ------------------------------------------------------------------
@app.route("/api/chat/availability", methods=["POST"])
def chat_availability():
    data = request.get_json(force=True) or {}
    product_id = data.get("product_id")
    if not product_id:
        return jsonify({"error": "product_id is required"}), 400

    product = _get_product_or_404(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    _log_chatbot_query(product_id, "availability", data.get("query_text", ""))

    if product["stock_level"] > 0:
        reply = f"'{product['name']}' is currently in stock ({product['stock_level']} units available)."
        return jsonify({
            "product_id": product_id,
            "in_stock": True,
            "stock_level": product["stock_level"],
            "message": reply,
        })

    eta = predictor.predict_restock_eta(product_id)
    admin_alert = _maybe_raise_admin_demand_alert(product_id)

    reply = (
        f"'{product['name']}' is currently out of stock. "
        f"Expected back in {eta['min_days']}\u2013{eta['max_days']} days "
        f"with {eta['confidence_pct']}% confidence. ({eta['explanation']})"
    )

    return jsonify({
        "product_id": product_id,
        "in_stock": False,
        "message": reply,
        "eta_min_days": eta["min_days"],
        "eta_max_days": eta["max_days"],
        "confidence_pct": eta["confidence_pct"],
        "supplier_name": eta["supplier_name"],
        "admin_alert_triggered": admin_alert is not None,
    })


# ------------------------------------------------------------------
# TASK 2 - ENDPOINT 2: Suggest Alternative Recommendations
# ------------------------------------------------------------------
@app.route("/api/chat/alternatives", methods=["POST"])
def chat_alternatives():
    data = request.get_json(force=True) or {}
    product_id = data.get("product_id")
    if not product_id:
        return jsonify({"error": "product_id is required"}), 400

    product = _get_product_or_404(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    _log_chatbot_query(product_id, "alternative", data.get("query_text", ""))

    alternatives = predictor.find_alternatives(product_id, limit=3)

    if not alternatives:
        message = f"Sorry, I couldn't find any similar in-stock alternatives to '{product['name']}' right now."
    else:
        names = ", ".join(f"{a['name']} ({a['match_score']}% match)" for a in alternatives)
        message = f"Here are some alternatives to '{product['name']}': {names}"

    return jsonify({
        "product_id": product_id,
        "message": message,
        "alternatives": alternatives,
    })


# ------------------------------------------------------------------
# TASK 2 - ENDPOINT 3: Customer Subscription Trigger
# ------------------------------------------------------------------
@app.route("/api/chat/subscribe", methods=["POST"])
def chat_subscribe():
    data = request.get_json(force=True) or {}
    product_id = data.get("product_id")
    email = (data.get("email") or "").strip() or None
    phone = (data.get("phone") or "").strip() or None

    if not product_id:
        return jsonify({"error": "product_id is required"}), 400
    if not email and not phone:
        return jsonify({"error": "Provide at least an email or phone number"}), 400

    product = _get_product_or_404(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    sub_id, _ = db.execute(
        """INSERT INTO customer_subscriptions (product_id, customer_email, customer_phone)
           VALUES (%s, %s, %s)""",
        (product_id, email, phone),
    )

    # Being subscribed also counts as an interest signal for the admin alert
    admin_alert = _maybe_raise_admin_demand_alert(product_id)

    return jsonify({
        "subscription_id": sub_id,
        "message": f"You're subscribed! We'll notify you as soon as '{product['name']}' is back in stock.",
        "admin_alert_triggered": admin_alert is not None,
    })


# ------------------------------------------------------------------
# ADMIN: Demand alert feed (read-only, feeds the dashboard)
# ------------------------------------------------------------------
@app.route("/api/admin/alerts", methods=["GET"])
def admin_alerts():
    rows = db.query(
        """SELECT a.*, p.name AS product_name, p.stock_level
           FROM admin_demand_alerts a
           JOIN products p ON p.product_id = a.product_id
           WHERE a.is_resolved = FALSE
           ORDER BY a.created_at DESC"""
    )
    return jsonify(rows)


# ------------------------------------------------------------------
# TASK 4: Admin restock action -> triggers customer notification loop
# ------------------------------------------------------------------
@app.route("/api/admin/restock", methods=["POST"])
def admin_restock():
    data = request.get_json(force=True) or {}
    product_id = data.get("product_id")
    new_stock_level = data.get("new_stock_level")

    if product_id is None or new_stock_level is None:
        return jsonify({"error": "product_id and new_stock_level are required"}), 400

    product = _get_product_or_404(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    was_out_of_stock = product["stock_level"] == 0

    db.execute(
        "UPDATE products SET stock_level = %s WHERE product_id = %s",
        (new_stock_level, product_id),
    )

    notified = []
    if was_out_of_stock and int(new_stock_level) > 0:
        subscribers = db.query(
            """SELECT * FROM customer_subscriptions
               WHERE product_id = %s AND notified = FALSE""",
            (product_id,),
        )
        for sub in subscribers:
            success = notifier.send_restock_notification(
                sub["customer_email"], sub["customer_phone"], product["name"], new_stock_level
            )
            if success:
                db.execute(
                    """UPDATE customer_subscriptions
                       SET notified = TRUE, notified_at = NOW()
                       WHERE subscription_id = %s""",
                    (sub["subscription_id"],),
                )
                notified.append(sub["customer_email"] or sub["customer_phone"])

        # Resolve any open high-interest alert for this product now that it's restocked
        db.execute(
            """UPDATE admin_demand_alerts SET is_resolved = TRUE
               WHERE product_id = %s AND alert_type = 'high_interest_oos'""",
            (product_id,),
        )

    return jsonify({
        "product_id": product_id,
        "new_stock_level": int(new_stock_level),
        "customers_notified": notified,
        "notified_count": len(notified),
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
