"""
HTTP API, expressed as one pure function so it can be mounted on anything.

    status, payload = api.handle("POST", "/api/chat", {}, {"message": "..."})

`server.py` mounts this on Flask when Flask is installed, and on the standard
library's http.server otherwise — the routes and JSON are identical either way.

TASK 2 ENDPOINTS
  POST /api/chat                 conversational entry point (all 4 features)
  POST /api/chat/availability    1. restock prediction for a product
  POST /api/chat/alternatives    2. similar in-stock products with match scores
  POST /api/chat/subscribe       3. save a restock subscription
  GET  /api/admin/alerts         4. the Admin Demand Log

SUPPORTING
  GET  /api/health, /api/products, /api/products/<id>
  GET  /api/admin/demand, /api/admin/subscriptions
  POST /api/admin/restock        restock an item + notify everyone waiting
  POST /api/admin/reset          rebuild the demo data
"""
from . import alerts, chatbot, config, db, predictor, similarity, subscriptions


def handle(method, path, params, body):
    params = params or {}
    body = body or {}
    path = path.rstrip("/") or "/"

    # ---------------------------------------------------------------- health
    if method == "GET" and path == "/api/health":
        ok, target = db.ping()
        counts = {}
        if ok:
            for table in ("products", "suppliers", "sales_log", "customer_subscriptions",
                          "chatbot_query_log", "admin_demand_alerts"):
                row = db.query(f"SELECT COUNT(*) AS n FROM {table}", fetchone=True)
                counts[table] = int(row["n"])
        return 200 if ok else 503, {
            "ok": ok,
            "engine": db.engine(),
            "database": target,
            "row_counts": counts,
            "high_interest_threshold": config.HIGH_INTEREST_THRESHOLD,
        }

    # ---------------------------------------------------------------- catalogue
    if method == "GET" and path == "/api/products":
        search = (params.get("q") or "").strip()
        if search:
            rows = similarity.search_products(search, limit=int(params.get("limit", 10)))
        else:
            rows = db.query("SELECT * FROM products ORDER BY stock_level ASC, name ASC")
        for row in rows:
            row["attributes"] = db.load_json(row.get("attributes"))
            row["price"] = float(row["price"])
        return 200, {"products": rows, "count": len(rows)}

    if method == "GET" and path.startswith("/api/products/"):
        try:
            product_id = int(path.rsplit("/", 1)[1])
        except ValueError:
            return 400, {"error": "product_id must be an integer"}
        product = db.query(
            "SELECT * FROM products WHERE product_id = %s", (product_id,), fetchone=True
        )
        if not product:
            return 404, {"error": "Product not found"}
        product["attributes"] = db.load_json(product.get("attributes"))
        product["price"] = float(product["price"])
        product["demand"] = alerts.demand_score(product_id)
        if int(product["stock_level"]) == 0:
            product["restock_prediction"] = predictor.predict_restock_eta(product_id)
        return 200, product

    # ---------------------------------------------------------------- chat
    if method == "POST" and path == "/api/chat":
        message = (body.get("message") or "").strip()
        if not message:
            return 400, {"error": "message is required"}
        return 200, chatbot.handle_message(body.get("session_id"), message)

    if method == "POST" and path == "/api/chat/availability":
        product, error = _require_product(body)
        if error:
            return error
        alerts.log_query(product["product_id"], "availability", body.get("query_text", ""))
        if int(product["stock_level"]) > 0:
            return 200, {
                "product_id": product["product_id"],
                "in_stock": True,
                "stock_level": int(product["stock_level"]),
                "message": f"'{product['name']}' is in stock "
                           f"({product['stock_level']} units available).",
            }
        eta = predictor.predict_restock_eta(product["product_id"])
        alert = alerts.evaluate_product(product["product_id"], reason="api_availability")
        return 200, {
            "product_id": product["product_id"],
            "in_stock": False,
            "message": f"'{product['name']}' is out of stock. Expected back in "
                       f"{eta['min_days']}–{eta['max_days']} days with "
                       f"{eta['confidence_pct']}% confidence.",
            "prediction": eta,
            "admin_alert_triggered": bool(alert and alert["is_new"]),
            "admin_alert": alert,
        }

    if method == "POST" and path == "/api/chat/alternatives":
        product, error = _require_product(body)
        if error:
            return error
        alerts.log_query(product["product_id"], "alternative", body.get("query_text", ""))
        items = similarity.find_alternatives(
            product["product_id"], limit=int(body.get("limit", config.MAX_ALTERNATIVES))
        )
        if items:
            summary = ", ".join(f"{i['name']} ({i['match_score']}% match)" for i in items)
            message = f"Alternatives to '{product['name']}': {summary}"
        else:
            message = f"No close in-stock alternatives to '{product['name']}' right now."
        return 200, {
            "product_id": product["product_id"],
            "message": message,
            "alternatives": items,
        }

    if method == "POST" and path == "/api/chat/subscribe":
        product, error = _require_product(body)
        if error:
            return error
        result, err = subscriptions.subscribe(
            product["product_id"], body.get("email"), body.get("phone")
        )
        if err:
            return 400, {"error": err}
        alerts.log_query(product["product_id"], "subscribe", body.get("query_text", ""))
        return 200, {
            **result,
            "message": f"Subscribed. We'll notify "
                       f"{result['email'] or result['phone']} when "
                       f"'{result['product_name']}' is back in stock.",
            "admin_alert_triggered": bool(result.get("admin_alert")
                                          and result["admin_alert"]["is_new"]),
        }

    # ---------------------------------------------------------------- admin
    if method == "GET" and path == "/api/admin/alerts":
        return 200, {"alerts": alerts.open_alerts(),
                     "threshold": config.HIGH_INTEREST_THRESHOLD}

    if method == "GET" and path == "/api/admin/demand":
        return 200, {"demand": alerts.demand_leaderboard(limit=int(params.get("limit", 8))),
                     "threshold": config.HIGH_INTEREST_THRESHOLD}

    if method == "GET" and path == "/api/admin/subscriptions":
        return 200, {"subscriptions": subscriptions.list_subscriptions(
            limit=int(params.get("limit", 25)))}

    if method == "POST" and path == "/api/admin/restock":
        product, error = _require_product(body)
        if error:
            return error
        new_level = body.get("new_stock_level")
        if new_level is None:
            return 400, {"error": "new_stock_level is required"}
        new_level = int(new_level)
        was_out = int(product["stock_level"]) == 0

        db.execute(
            "UPDATE products SET stock_level = %s WHERE product_id = %s",
            (new_level, product["product_id"]),
        )
        similarity.invalidate_cache()

        notifications, resolved = [], 0
        if was_out and new_level > 0:
            notifications = subscriptions.notify_waiting(product["product_id"], new_level)
            resolved = alerts.resolve_for_product(product["product_id"])

        return 200, {
            "product_id": product["product_id"],
            "product_name": product["name"],
            "new_stock_level": new_level,
            "notifications": notifications,
            "notified_count": len(notifications),
            "alerts_resolved": resolved,
        }

    if method == "POST" and path == "/api/admin/reset":
        from . import seed

        seed.reset_and_seed(verbose=False)
        similarity.invalidate_cache()
        chatbot._SESSIONS.clear()
        return 200, {"ok": True, "message": "Demo data rebuilt."}

    return 404, {"error": f"No route for {method} {path}"}


def _require_product(body):
    """Resolve product_id (or a product name) from a request body."""
    product_id = body.get("product_id")
    if product_id is None and body.get("product_name"):
        matches = similarity.search_products(body["product_name"], limit=1)
        if not matches:
            return None, (404, {"error": "Product not found"})
        product_id = matches[0]["product_id"]
    if product_id is None:
        return None, (400, {"error": "product_id is required"})
    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        return None, (400, {"error": "product_id must be an integer"})

    product = db.query(
        "SELECT * FROM products WHERE product_id = %s", (product_id,), fetchone=True
    )
    if not product:
        return None, (404, {"error": "Product not found"})
    return product, None
