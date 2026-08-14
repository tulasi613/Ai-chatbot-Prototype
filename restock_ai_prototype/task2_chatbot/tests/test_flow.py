#!/usr/bin/env python3
"""
End-to-end checks for all four Task-2 capabilities.

    python3 tests/test_flow.py

Runs against a throwaway SQLite file, so your demo database is untouched.
No pytest required.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Point at a scratch database BEFORE the app config is imported.
TMP_DB = Path(tempfile.gettempdir()) / "restock_ai_test.db"
if TMP_DB.exists():
    TMP_DB.unlink()
os.environ["SQLITE_PATH"] = str(TMP_DB)
os.environ["DB_ENGINE"] = "sqlite"

from app import alerts, api, chatbot, db, init_db, nlu, predictor, seed, similarity  # noqa: E402

PASSED, FAILED = 0, 0


def check(label, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  \033[32mPASS\033[0m  {label}")
    else:
        FAILED += 1
        print(f"  \033[31mFAIL\033[0m  {label} {detail}")


def section(title):
    print(f"\n\033[1m{title}\033[0m")


# ------------------------------------------------------------------ setup
init_db.create_schema(verbose=False)
seed.reset_and_seed(verbose=False)
OOS_ID = 4        # Smart Fitness Watch (out of stock)
IN_STOCK_ID = 2   # Wireless Earbuds Pro


# ------------------------------------------------------------------ 1. prediction
section("1. Predict availability")
eta = predictor.predict_restock_eta(OOS_ID)
check("returns a restock window", eta and eta["min_days"] >= 1)
check("window is ordered", eta["min_days"] < eta["max_days"], f"got {eta}")
check("confidence is a sane percentage", 45 <= eta["confidence_pct"] <= 97,
      f"got {eta['confidence_pct']}")
check("names the supplier", bool(eta["supplier_name"]))
check("explains its factors", len(eta["factors"]) >= 3)
check("dates match the day window", eta["eta_from"] < eta["eta_to"])

velocity, active_days = predictor.sales_velocity(OOS_ID, days=30)
check("computes sales velocity from history", velocity > 0, f"got {velocity}")
check("counts days of sales history", active_days > 10, f"got {active_days}")

no_supplier = predictor.predict_restock_eta(999999)
check("unknown product returns None", no_supplier is None)


# ------------------------------------------------------------------ 2. alternatives
section("2. Alternative recommendations (vector similarity)")
alts = similarity.find_alternatives(OOS_ID)
check("returns up to 3 alternatives", 1 <= len(alts) <= 3, f"got {len(alts)}")
check("every alternative is in stock", all(a["stock_level"] > 0 for a in alts))
check("never recommends the product itself", all(a["product_id"] != OOS_ID for a in alts))
check("scores are sorted high to low",
      [a["match_score"] for a in alts] == sorted((a["match_score"] for a in alts), reverse=True))
check("scores stay within 0-100", all(0 <= a["match_score"] <= 100 for a in alts))
check("closest match beats 60%", alts[0]["match_score"] > 60, f"got {alts[0]['match_score']}")
check("explains why it matched", all(a["reasons"] for a in alts))
check("exposes the score breakdown",
      all({"vector_similarity", "attribute_overlap", "price_closeness"} <= set(a["breakdown"])
          for a in alts))

watch_alts = [a["name"] for a in alts]
check("smartwatch matches the other smartwatch first",
      "Sport GPS Smartwatch" == alts[0]["name"], f"got {watch_alts}")


# ------------------------------------------------------------------ 3. subscriptions
section("3. Customer subscription capture")
result, error = api.handle("POST", "/api/chat/subscribe", {},
                           {"product_id": OOS_ID, "email": "test@example.com"})[1], None
check("subscription is saved", result.get("subscription_id") is not None, str(result))
check("confirmation names the product", "Smart Fitness Watch" in result["message"])

row = db.query("SELECT * FROM customer_subscriptions WHERE subscription_id = %s",
               (result["subscription_id"],), fetchone=True)
check("row landed in customer_subscriptions", row and row["customer_email"] == "test@example.com")
check("row starts un-notified", not row["notified"])

dupe, _ = api.handle("POST", "/api/chat/subscribe", {},
                     {"product_id": OOS_ID, "email": "test@example.com"})[1], None
check("duplicate signup is de-duplicated", dupe["subscription_id"] == result["subscription_id"])

status, bad = api.handle("POST", "/api/chat/subscribe", {},
                         {"product_id": OOS_ID, "email": "not-an-email"})
check("invalid email is rejected", status == 400, f"got {status} {bad}")

status, missing = api.handle("POST", "/api/chat/subscribe", {}, {"product_id": OOS_ID})
check("missing contact detail is rejected", status == 400)

email, phone = nlu.subscriptions.extract_contact("sure, ping me at a.b@c.co or +1 555 019 2837")
check("extracts an email from free text", email == "a.b@c.co", f"got {email}")
check("extracts a phone from free text", phone and "555" in phone, f"got {phone}")


# ------------------------------------------------------------------ 4. admin demand alert
section("4. Admin demand alert")
fresh_id = 14  # Adjustable Dumbbell Set — seeded well below the threshold
before = alerts.demand_score(fresh_id)
check("starts below the alert threshold", before["score"] < before["threshold"],
      f"got {before}")
check("no alert exists yet",
      not any(a["product_id"] == fresh_id for a in alerts.open_alerts()))

for _ in range(3):
    api.handle("POST", "/api/chat/availability", {}, {"product_id": fresh_id})
api.handle("POST", "/api/chat/subscribe", {},
           {"product_id": fresh_id, "email": "keen@example.com"})

after = alerts.demand_score(fresh_id)
check("interest accumulates from chat + subscription", after["score"] > before["score"],
      f"{before['score']} -> {after['score']}")
open_now = [a for a in alerts.open_alerts() if a["product_id"] == fresh_id]
check("alert is raised once the threshold is crossed", len(open_now) == 1, str(open_now))
check("alert records the interest count", open_now and open_now[0]["interest_count"] >= 6)

api.handle("POST", "/api/chat/availability", {}, {"product_id": fresh_id})
check("alert is refreshed, never duplicated",
      len([a for a in alerts.open_alerts() if a["product_id"] == fresh_id]) == 1)

check("in-stock products never raise an alert",
      alerts.evaluate_product(IN_STOCK_ID) is None)


# ------------------------------------------------------------------ 5. restock loop
section("5. Restock closes the loop")
status, restock = api.handle("POST", "/api/admin/restock", {},
                             {"product_id": OOS_ID, "new_stock_level": 25})
check("stock level is updated", restock["new_stock_level"] == 25)
check("waiting customers are notified", restock["notified_count"] >= 1, str(restock))
check("notification names the product",
      all("Smart Fitness Watch" in n["body"] for n in restock["notifications"]))
check("open alerts are resolved", restock["alerts_resolved"] >= 1)
check("subscriptions are marked notified",
      db.query("SELECT COUNT(*) AS n FROM customer_subscriptions "
               "WHERE product_id = %s AND notified = 0", (OOS_ID,), fetchone=True)["n"] == 0)
check("restocked product is no longer in the demand list",
      not any(d["product_id"] == OOS_ID for d in alerts.demand_leaderboard()))


# ------------------------------------------------------------------ 6. NLU
section("6. Natural language understanding")
INTENT_CASES = [
    ("hi there", "greeting"),
    ("thanks!", "thanks"),
    ("what can you do?", "help"),
    ("what else is out of stock?", "browse"),
    ("when will the running jacket be back?", "availability"),
    ("is the merino beanie available", "availability"),
    ("show me something similar to the frying pan set", "alternatives"),
    ("notify me when it's back", "subscribe"),
    ("email me at x@y.com", "subscribe"),
    ("how did you predict that", "explain"),
    ("how much is the electric kettle", "price"),
]
for text, expected in INTENT_CASES:
    got = nlu.understand(text, {"product_id": 11})["intent"]
    check(f"'{text}' -> {expected}", got == expected, f"got '{got}'")

resolved = nlu.resolve_product("wireless noise cancelling headphones")[0]
check("resolves a full product name", resolved and resolved["product_id"] == 1)
resolved = nlu.resolve_product("merino beanie")[0]
check("resolves a partial product name", resolved and resolved["product_id"] == 9)
unknown, candidates = nlu.resolve_product("quantum flux capacitor")
check("unknown text resolves to nothing", unknown is None and not candidates)


# ------------------------------------------------------------------ 7. conversation
section("7. Full conversation over the chat endpoint")
session = "test-session"


def say(message):
    return api.handle("POST", "/api/chat", {}, {"session_id": session, "message": message})[1]


turn = say("hi")
check("greeting turn suggests products", turn["intent"] == "greeting" and turn["quick_replies"])

# Two products match "vitamin c serum", so the bot should ask which one.
turn = say("when will the vitamin c serum be back?")
check("ambiguous product asks for clarification", turn["intent"] == "clarify", turn["intent"])
check("clarification offers the candidates", len(turn["quick_replies"]) >= 2)

turn = say("Vitamin C Brightening Serum")
kinds = [b["type"] for b in turn["reply"]]
check("availability turn returns a prediction", "prediction" in kinds, str(kinds))
check("availability turn offers alternatives", "alternatives" in kinds, str(kinds))
check("availability turn shows the product card", "product" in kinds)

turn = say("how did you predict that?")
check("follow-up keeps the product in context",
      turn["context"]["product_id"] == 16, str(turn["context"]))

turn = say("notify me")
check("asks for contact details",
      any(b["type"] == "subscribe_form" for b in turn["reply"]), str(turn["reply"]))

turn = say("vivek@example.com")
check("captures the contact and confirms",
      any(b["type"] == "subscription_confirmed" for b in turn["reply"]))
check("records the demand signal", turn["context"]["demand"]["subscriptions"] >= 1)

turn = say("show me alternatives")
check("context carries into the alternatives request",
      any(b["type"] == "alternatives" for b in turn["reply"]))

turn = say("tell me about the fluxinator 9000")
check("unknown product asks for clarification", turn["intent"] in ("unknown", "clarify"))


# ------------------------------------------------------------------ 8. API surface
section("8. REST surface")
status, health = api.handle("GET", "/api/health", {}, {})
check("health endpoint reports ok", status == 200 and health["ok"])
check("health reports row counts", health["row_counts"]["products"] == 24)

status, products = api.handle("GET", "/api/products", {}, {})
check("product list works", status == 200 and products["count"] == 24)

status, found = api.handle("GET", "/api/products", {"q": "beanie"}, {})
check("product search works", any("Beanie" in p["name"] for p in found["products"]))

status, detail = api.handle("GET", "/api/products/9", {}, {})
check("product detail includes a prediction",
      status == 200 and "restock_prediction" in detail)
check("product detail parses the JSON attributes", isinstance(detail["attributes"], dict))

status, _ = api.handle("GET", "/api/products/99999", {}, {})
check("missing product returns 404", status == 404)

status, _ = api.handle("POST", "/api/chat", {}, {"message": ""})
check("empty chat message returns 400", status == 400)

status, _ = api.handle("GET", "/api/nope", {}, {})
check("unknown route returns 404", status == 404)


# ------------------------------------------------------------------ summary
print(f"\n{'=' * 52}")
print(f"  {PASSED} passed, {FAILED} failed")
print(f"{'=' * 52}\n")
sys.exit(1 if FAILED else 0)
