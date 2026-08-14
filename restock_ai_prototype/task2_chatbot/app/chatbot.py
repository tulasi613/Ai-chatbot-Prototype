"""
Conversation orchestration.

`handle_message()` turns one customer message into a structured turn:

    {
      "reply":  [ {"type": "text" | "prediction" | "alternatives" | ...} ],
      "quick_replies": [...],
      "events": [...],        # side effects the live admin panel renders
      "context": {...}
    }

The UI renders blocks; the API tests read the same JSON. All four Task-2
capabilities are reachable from plain English in this one endpoint, and each is
also exposed as its own REST endpoint in api.py.
"""
import threading
import uuid
from datetime import datetime, timedelta

from . import alerts, config, db, nlu, predictor, similarity, subscriptions

_SESSIONS = {}
_SESSION_LOCK = threading.Lock()
_SESSION_TTL = timedelta(hours=2)


# ------------------------------------------------------------------ sessions
def get_session(session_id):
    with _SESSION_LOCK:
        now = datetime.now()
        for sid, data in list(_SESSIONS.items()):
            if now - data["_touched"] > _SESSION_TTL:
                _SESSIONS.pop(sid, None)

        if not session_id or session_id not in _SESSIONS:
            session_id = session_id or f"s-{uuid.uuid4().hex[:12]}"
            _SESSIONS[session_id] = {"_touched": now, "id": session_id}
        session = _SESSIONS[session_id]
        session["_touched"] = now
        return session


# ------------------------------------------------------------------ block helpers
def _text(message):
    return {"type": "text", "text": message}


def _product_block(product):
    return {
        "type": "product",
        "product_id": product["product_id"],
        "name": product["name"],
        "category": product["category"],
        "price": float(product["price"]),
        "stock_level": int(product["stock_level"]),
        "image_url": product.get("image_url"),
    }


def _quick(label, message, style="default"):
    return {"label": label, "message": message, "style": style}


def _trending_oos(limit=4):
    rows = alerts.demand_leaderboard(limit=limit)
    return [_quick(row["name"], f"When will {row['name']} be back in stock?") for row in rows]


# ------------------------------------------------------------------ capabilities
def answer_availability(product, session, query_text=""):
    """Feature 1: availability + restock prediction."""
    alerts.log_query(product["product_id"], "availability", query_text)
    blocks = [_product_block(product)]
    events = []

    if int(product["stock_level"]) > 0:
        cover = predictor.days_of_cover(product["product_id"], int(product["stock_level"]))
        line = (
            f"Good news — **{product['name']}** is in stock right now "
            f"({product['stock_level']} units, ${float(product['price']):.2f})."
        )
        if cover is not None and cover <= 7:
            line += (
                f" Heads up: at the current selling pace that's only about "
                f"{cover:.0f} more days of stock."
            )
        blocks.insert(0, _text(line))
        quick_replies = [
            _quick("Show similar products", f"Show me alternatives to {product['name']}"),
            _quick("Something else", "What else is out of stock?"),
        ]
        session["pending"] = "offer_alternatives"
        return blocks, quick_replies, events

    # --- out of stock: predict, recommend, then offer the subscription ---
    eta = predictor.predict_restock_eta(product["product_id"])
    alert = alerts.evaluate_product(product["product_id"], reason="availability_query")

    blocks.insert(0, _text(
        f"**{product['name']}** is currently out of stock — but I can tell you when "
        f"it's coming back."
    ))
    blocks.append({
        "type": "prediction",
        "product_id": product["product_id"],
        "product_name": product["name"],
        "headline": f"Expected back in {eta['min_days']}–{eta['max_days']} days "
                    f"with {eta['confidence_pct']}% confidence",
        **eta,
    })

    alternatives = similarity.find_alternatives(product["product_id"])
    if alternatives:
        alerts.log_query(product["product_id"], "alternative", query_text)
        blocks.append(_text(
            f"If you'd rather not wait, these {len(alternatives)} in-stock options are "
            f"the closest matches:"
        ))
        blocks.append({
            "type": "alternatives",
            "product_id": product["product_id"],
            "items": alternatives,
        })

    waiting = subscriptions.count_waiting(product["product_id"])
    waiting_note = {
        0: "",
        1: " 1 other customer is already waiting.",
    }.get(waiting, f" {waiting} other customers are already waiting.")
    blocks.append(_text(
        f"Want me to email or text you the moment it lands?{waiting_note}"
    ))

    if alert:
        events.append({
            "type": "admin_alert",
            "is_new": alert["is_new"],
            "product_name": alert["product_name"],
            "interest_count": alert["interest_count"],
            "message": alert["alert_message"],
        })
        if alert["is_new"]:
            blocks.append(_text(
                "_I've also flagged this to the inventory team — you're not the only "
                "one asking about it._"
            ))

    session["pending"] = "offer_subscribe"
    quick_replies = [
        _quick("Notify me when it's back", "Notify me when it's back in stock", "primary"),
        _quick("Show alternatives", f"Show me alternatives to {product['name']}"),
        _quick("How did you predict that?", "explain the prediction"),
    ]
    return blocks, quick_replies, events


def answer_alternatives(product, session, query_text=""):
    """Feature 2: vector-similarity recommendations."""
    alerts.log_query(product["product_id"], "alternative", query_text)
    alternatives = similarity.find_alternatives(product["product_id"])
    events = []

    if not alternatives:
        return (
            [_text(f"I couldn't find a close in-stock match for **{product['name']}** "
                   f"right now. I can let you know as soon as it's restocked instead.")],
            [_quick("Notify me when it's back", "Notify me when it's back in stock", "primary")],
            events,
        )

    best = alternatives[0]
    blocks = [
        _text(
            f"Here {'is' if len(alternatives) == 1 else 'are'} {len(alternatives)} "
            f"in-stock alternative{'' if len(alternatives) == 1 else 's'} to "
            f"**{product['name']}** — **{best['name']}** is the closest at "
            f"{best['match_score']}% match."
        ),
        {"type": "alternatives", "product_id": product["product_id"], "items": alternatives},
    ]

    quick_replies = [_quick(f"Is {best['name']} in stock?", f"Is {best['name']} available?")]
    if int(product["stock_level"]) == 0:
        session["pending"] = "offer_subscribe"
        quick_replies.insert(
            0, _quick("Notify me when it's back", "Notify me when it's back in stock", "primary")
        )
    return blocks, quick_replies, events


def answer_subscribe(product, session, email, phone, query_text=""):
    """Feature 3: capture the contact detail and save the subscription."""
    events = []

    if int(product["stock_level"]) > 0:
        return (
            [_text(f"**{product['name']}** is in stock right now — no need to wait! "
                   f"{product['stock_level']} units are available.")],
            [_quick("Show similar products", f"Show me alternatives to {product['name']}")],
            events,
        )

    if not (email or phone):
        session["pending"] = "awaiting_contact"
        session["product_id"] = product["product_id"]
        return (
            [
                _text(f"Sure — what's the best way to reach you when "
                      f"**{product['name']}** is back? An email address or mobile number works."),
                {
                    "type": "subscribe_form",
                    "product_id": product["product_id"],
                    "product_name": product["name"],
                },
            ],
            [],
            events,
        )

    alerts.log_query(product["product_id"], "subscribe", query_text)
    result, error = subscriptions.subscribe(product["product_id"], email, phone)
    if error:
        session["pending"] = "awaiting_contact"
        return ([_text(error)], [], events)

    contact = result["email"] or result["phone"]
    if result["duplicate"]:
        line = (f"You're already on the list for **{result['product_name']}** — "
                f"we'll reach out at {contact}.")
    else:
        line = (f"Done! I'll notify **{contact}** the moment **{result['product_name']}** "
                f"is back in stock.")

    blocks = [
        _text(line),
        {
            "type": "subscription_confirmed",
            "subscription_id": result["subscription_id"],
            "product_id": result["product_id"],
            "product_name": result["product_name"],
            "contact": contact,
            "channel": "email" if result["email"] else "sms",
            "total_waiting": result["total_waiting"],
            "duplicate": result["duplicate"],
        },
    ]

    alert = result.get("admin_alert")
    if alert:
        events.append({
            "type": "admin_alert",
            "is_new": alert["is_new"],
            "product_name": alert["product_name"],
            "interest_count": alert["interest_count"],
            "message": alert["alert_message"],
        })
        waiting = result["total_waiting"]
        blocks.append(_text(
            f"_Demand alert raised for the inventory team — {waiting} "
            f"customer{'' if waiting == 1 else 's'} now waiting on this item._"
        ))

    session["pending"] = None
    alternatives = similarity.find_alternatives(product["product_id"], limit=2)
    quick_replies = []
    if alternatives:
        quick_replies.append(
            _quick("Meanwhile, show alternatives", f"Show me alternatives to {product['name']}")
        )
    quick_replies.append(_quick("Ask about another product", "What else is out of stock?"))
    return blocks, quick_replies, events


def explain_prediction(product):
    eta = predictor.predict_restock_eta(product["product_id"])
    if not eta:
        return [_text("I don't have prediction data for that product.")], [], []
    lines = "\n".join(
        f"• **{f['label']}** — {f['detail']}" + (f" ({f['value']})" if f.get("value") else "")
        for f in eta["factors"]
    )
    return (
        [
            _text(f"Here's how I estimated **{product['name']}**'s "
                  f"{eta['min_days']}–{eta['max_days']} day window:\n\n{lines}"),
            {"type": "prediction", "product_id": product["product_id"],
             "product_name": product["name"],
             "headline": f"Expected back in {eta['min_days']}–{eta['max_days']} days "
                         f"with {eta['confidence_pct']}% confidence", **eta},
        ],
        [_quick("Notify me when it's back", "Notify me when it's back in stock", "primary")],
        [],
    )


def browse_out_of_stock():
    rows = alerts.demand_leaderboard(limit=8)
    blocks = [
        _text("These items are currently out of stock — the ones at the top are the "
              "most in demand. Ask me about any of them:"),
        {"type": "catalog", "items": rows},
    ]
    return blocks, _trending_oos(), []


# ------------------------------------------------------------------ main entry
def handle_message(session_id, message):
    session = get_session(session_id)
    parsed = nlu.understand(message, session)
    intent = parsed["intent"]
    product = parsed["product"]
    events = []

    if product:
        session["product_id"] = product["product_id"]

    # ---- intents that don't need a product -------------------------------
    if intent == "greeting":
        session["pending"] = None
        blocks = [_text(
            "Hi! I'm the Restock Assistant. I can tell you **when an out-of-stock item "
            "is coming back**, suggest **in-stock alternatives**, and **notify you** "
            "personally the moment it lands. Which product are you after?"
        )]
        return _turn(session, intent, blocks, _trending_oos(), events)

    if intent == "help":
        blocks = [_text(
            "Here's what I can do:\n\n"
            "• **Availability** — \"When will the Smart Fitness Watch be back?\"\n"
            "• **Alternatives** — \"Show me something similar to the running jacket\"\n"
            "• **Restock alerts** — \"Notify me at you@example.com\"\n\n"
            "I also flag high-demand items to the inventory team automatically."
        )]
        return _turn(session, intent, blocks, _trending_oos(), events)

    if intent == "thanks":
        return _turn(session, intent, [_text("Anytime! Anything else I can check for you?")],
                     _trending_oos(3), events)

    if intent == "browse":
        session["pending"] = None
        blocks, quick, events = browse_out_of_stock()
        return _turn(session, intent, blocks, quick, events)

    if intent == "decline":
        session["pending"] = None
        return _turn(session, intent,
                     [_text("No problem. I'm here if you want to check another product.")],
                     _trending_oos(3), events)

    # ---- everything below needs a product --------------------------------
    if not product:
        if parsed["candidates"]:
            options = [
                _quick(c["name"], f"When will {c['name']} be back in stock?")
                for c in parsed["candidates"]
            ]
            blocks = [_text("I found a few products that could match — which one did you mean?")]
            return _turn(session, "clarify", blocks, options, events)

        blocks = [_text(
            "I couldn't match that to a product in our catalogue. Try the product name "
            "(for example *\"Smart Fitness Watch\"*), or tap one of the popular "
            "out-of-stock items below."
        )]
        return _turn(session, "unknown", blocks, _trending_oos(), events)

    if intent == "subscribe":
        blocks, quick, events = answer_subscribe(
            product, session, parsed["email"], parsed["phone"], parsed["text"]
        )
    elif intent == "alternatives":
        blocks, quick, events = answer_alternatives(product, session, parsed["text"])
    elif intent == "price":
        stock = int(product["stock_level"])
        state = f"{stock} in stock" if stock else "currently out of stock"
        blocks = [
            _text(f"**{product['name']}** is ${float(product['price']):.2f} — {state}."),
            _product_block(product),
        ]
        quick = [_quick("When is it back?", f"When will {product['name']} be back in stock?")] \
            if not stock else [_quick("Show similar", f"Alternatives to {product['name']}")]
    elif intent == "explain":
        blocks, quick, events = explain_prediction(product)
    else:  # availability is the default reading of a product mention
        blocks, quick, events = answer_availability(product, session, parsed["text"])
        intent = "availability"

    return _turn(session, intent, blocks, quick, events)


def _turn(session, intent, blocks, quick_replies, events):
    product_id = session.get("product_id")
    context = {
        "product_id": product_id,
        "pending": session.get("pending"),
    }
    if product_id:
        context["demand"] = alerts.demand_score(product_id)
    return {
        "session_id": session["id"],
        "intent": intent,
        "reply": blocks,
        "quick_replies": quick_replies,
        "events": events,
        "context": context,
        "engine": db.engine(),
        "threshold": config.HIGH_INTEREST_THRESHOLD,
    }
