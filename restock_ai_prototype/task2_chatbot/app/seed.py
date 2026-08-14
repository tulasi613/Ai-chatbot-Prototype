"""
Demo catalogue + history.

Sales history, subscriptions and chat interest are generated *relative to today*
(with a fixed random seed, so every run produces the same numbers) — that keeps
the 14/30-day prediction windows populated no matter when the demo is run.
"""
import json
import random
from datetime import date, datetime, timedelta

from . import db

SUPPLIERS = [
    # (id, name, avg_lead_time_days, reliability_score, last_delivery_days_ago, email)
    (1, "NorthPeak Distribution", 5, 96.5, 8, "orders@northpeak.com"),
    (2, "Global Fabric Co.", 10, 88.2, 11, "sales@globalfabric.com"),
    (3, "QuickTech Wholesale", 4, 93.0, 5, "b2b@quicktech.com"),
    (4, "HomeGoods Direct", 8, 91.75, 13, "orders@homegoodsdirect.com"),
    (5, "PureGlow Cosmetics Supply", 6, 85.4, 10, "wholesale@pureglow.com"),
]

# (id, name, category, price, stock, attributes, supplier_id, reorder_threshold, base_daily_demand)
PRODUCTS = [
    (1, "Wireless Noise-Cancelling Headphones", "Electronics", 129.99, 0,
     {"color": "black", "connectivity": "bluetooth", "noise_cancelling": True,
      "battery_life_hrs": 30, "form": "over-ear"}, 3, 5, 2.6),
    (2, "Wireless Earbuds Pro", "Electronics", 89.99, 24,
     {"color": "white", "connectivity": "bluetooth", "noise_cancelling": True,
      "battery_life_hrs": 20, "form": "in-ear"}, 3, 8, 1.9),
    (3, "Over-Ear Studio Headphones", "Electronics", 149.99, 12,
     {"color": "silver", "connectivity": "wired", "noise_cancelling": False,
      "battery_life_hrs": 0, "form": "over-ear"}, 3, 5, 1.0),
    (4, "Smart Fitness Watch", "Electronics", 199.99, 0,
     {"color": "black", "water_resistant": True, "gps": True,
      "heart_rate": True, "battery_life_hrs": 168}, 3, 6, 2.4),
    (5, "Fitness Band Lite", "Electronics", 59.99, 33,
     {"color": "blue", "water_resistant": True, "gps": False,
      "heart_rate": True, "battery_life_hrs": 240}, 3, 10, 1.4),
    (6, "Men's Running Jacket", "Apparel", 74.99, 0,
     {"color": "navy", "size": "M", "material": "polyester",
      "waterproof": True, "fit": "athletic"}, 2, 8, 2.1),
    (7, "Men's Windbreaker", "Apparel", 64.99, 18,
     {"color": "navy", "size": "M", "material": "nylon",
      "waterproof": True, "fit": "athletic"}, 2, 8, 1.2),
    (8, "Women's Yoga Leggings", "Apparel", 39.99, 45,
     {"color": "black", "size": "S", "material": "spandex-blend", "fit": "slim"}, 2, 12, 1.6),
    (9, "Unisex Merino Wool Beanie", "Apparel", 24.99, 0,
     {"color": "grey", "size": "one-size", "material": "merino wool", "season": "winter"}, 2, 10, 1.7),
    (10, "Stainless Steel Cookware Set (10pc)", "Home & Kitchen", 189.99, 7,
     {"material": "stainless steel", "pieces": 10, "dishwasher_safe": True,
      "induction_ready": True}, 4, 4, 0.4),
    (11, "Non-Stick Frying Pan Set (3pc)", "Home & Kitchen", 59.99, 0,
     {"material": "non-stick aluminium", "pieces": 3, "dishwasher_safe": True,
      "induction_ready": True}, 4, 6, 2.2),
    (12, "Electric Kettle 1.7L", "Home & Kitchen", 34.99, 22,
     {"material": "stainless steel", "capacity_l": 1.7, "auto_shutoff": True}, 4, 8, 0.8),
    (13, "Insulated Yoga Mat", "Sports & Outdoors", 29.99, 40,
     {"color": "purple", "thickness_mm": 6, "material": "TPE", "use": "yoga"}, 1, 10, 1.1),
    (14, "Adjustable Dumbbell Set", "Sports & Outdoors", 149.99, 0,
     {"weight_range_kg": "2-20", "adjustable": True, "material": "steel/rubber",
      "use": "strength"}, 1, 5, 1.6),
    (15, "Hydro Flask Water Bottle 32oz", "Sports & Outdoors", 44.99, 3,
     {"color": "teal", "capacity_oz": 32, "insulated": True, "material": "steel"}, 1, 10, 1.8),
    (16, "Vitamin C Brightening Serum", "Beauty", 27.99, 0,
     {"volume_ml": 30, "skin_type": "all", "key_ingredient": "vitamin c",
      "cruelty_free": True}, 5, 12, 2.7),
    (17, "Hyaluronic Acid Moisturizer", "Beauty", 22.99, 31,
     {"volume_ml": 50, "skin_type": "dry", "key_ingredient": "hyaluronic acid",
      "cruelty_free": True}, 5, 12, 0.9),
    # --- extra in-stock products so every OOS item has real alternatives ---
    (18, "Studio Wireless Headphones Air", "Electronics", 139.99, 15,
     {"color": "black", "connectivity": "bluetooth", "noise_cancelling": True,
      "battery_life_hrs": 28, "form": "over-ear"}, 3, 5, 1.3),
    (19, "Sport GPS Smartwatch", "Electronics", 179.99, 9,
     {"color": "black", "water_resistant": True, "gps": True,
      "heart_rate": True, "battery_life_hrs": 120}, 3, 5, 1.1),
    (20, "Ceramic Non-Stick Pan Set (3pc)", "Home & Kitchen", 64.99, 14,
     {"material": "non-stick ceramic", "pieces": 3, "dishwasher_safe": True,
      "induction_ready": True}, 4, 6, 0.9),
    (21, "Cable-Knit Wool Blend Beanie", "Apparel", 21.99, 26,
     {"color": "grey", "size": "one-size", "material": "wool blend", "season": "winter"}, 2, 10, 1.0),
    (22, "Cast Iron Kettlebell Set (4-16kg)", "Sports & Outdoors", 129.99, 11,
     {"weight_range_kg": "4-16", "adjustable": False, "material": "cast iron",
      "use": "strength"}, 1, 5, 0.7),
    (23, "Vitamin C + Ferulic Glow Serum", "Beauty", 32.99, 19,
     {"volume_ml": 30, "skin_type": "all", "key_ingredient": "vitamin c",
      "cruelty_free": True}, 5, 10, 1.2),
    (24, "Softshell Trail Jacket", "Apparel", 84.99, 12,
     {"color": "black", "size": "M", "material": "softshell",
      "waterproof": True, "fit": "athletic"}, 2, 6, 0.8),
]

# Pre-existing chat interest: product_id -> number of logged queries
SEED_QUERIES = {1: 5, 4: 4, 6: 2, 9: 2, 11: 3, 14: 1, 16: 3}

# Pre-existing "notify me" subscriptions
SEED_SUBSCRIPTIONS = [
    (1, "priya.sharma@example.com", "+1-555-0101"),
    (1, "j.oconnor@example.com", None),
    (6, "d.mueller@example.com", None),
    (16, "grace.liu@example.com", None),
]


def _image_url(pid):
    return f"https://picsum.photos/seed/restock{pid}/400/400"


def seed_all(verbose=True):
    rng = random.Random(42)
    today = date.today()

    def say(msg):
        if verbose:
            print(msg)

    # ---------------------------------------------------------- suppliers
    db.executemany(
        """INSERT INTO suppliers
           (supplier_id, supplier_name, avg_lead_time_days, reliability_score,
            last_delivery_date, contact_email)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        [
            (sid, name, lead, rel, (today - timedelta(days=ago)).isoformat(), email)
            for sid, name, lead, rel, ago, email in SUPPLIERS
        ],
    )
    say(f"  suppliers          : {len(SUPPLIERS)}")

    # ---------------------------------------------------------- products
    db.executemany(
        """INSERT INTO products
           (product_id, name, category, price, stock_level, attributes,
            image_url, supplier_id, reorder_threshold)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        [
            (pid, name, cat, price, stock, json.dumps(attrs), _image_url(pid), sup, thr)
            for pid, name, cat, price, stock, attrs, sup, thr, _ in PRODUCTS
        ],
    )
    say(f"  products           : {len(PRODUCTS)}  ({sum(1 for p in PRODUCTS if p[4] == 0)} out of stock)")

    # ---------------------------------------------------------- sales history (60 days)
    sales = []
    for pid, _name, _cat, price, stock, _attrs, _sup, _thr, base in PRODUCTS:
        for days_ago in range(60, 0, -1):
            day = today - timedelta(days=days_ago)
            # Out-of-stock items stop selling once they run dry (~last 4 days).
            if stock == 0 and days_ago <= 4:
                continue
            weekend_boost = 1.35 if day.weekday() >= 5 else 1.0
            trend = 1.0 + (60 - days_ago) / 300.0  # mild upward demand trend
            expected = base * weekend_boost * trend
            qty = max(0, int(rng.gauss(expected, expected * 0.45) + 0.5))
            if qty:
                sales.append((pid, day.isoformat(), qty, price))
    db.executemany(
        """INSERT INTO sales_log (product_id, sale_date, quantity_sold, unit_price)
           VALUES (%s, %s, %s, %s)""",
        sales,
    )
    say(f"  sales_log rows     : {len(sales)}  (60 days of history)")

    # ---------------------------------------------------------- chat interest
    queries = []
    for pid, count in SEED_QUERIES.items():
        name = next(p[1] for p in PRODUCTS if p[0] == pid)
        for i in range(count):
            when = datetime.now() - timedelta(days=rng.randint(1, 12), hours=rng.randint(0, 20))
            queries.append((
                pid,
                "availability",
                f"when will {name.lower()} be back in stock?",
                when.strftime("%Y-%m-%d %H:%M:%S"),
            ))
    db.executemany(
        """INSERT INTO chatbot_query_log (product_id, query_type, query_text, queried_at)
           VALUES (%s, %s, %s, %s)""",
        queries,
    )
    say(f"  chatbot_query_log  : {len(queries)}")

    # ---------------------------------------------------------- subscriptions
    subs = []
    for pid, email, phone in SEED_SUBSCRIPTIONS:
        when = datetime.now() - timedelta(days=rng.randint(1, 9))
        subs.append((pid, email, phone, when.strftime("%Y-%m-%d %H:%M:%S")))
    db.executemany(
        """INSERT INTO customer_subscriptions
           (product_id, customer_email, customer_phone, subscribed_at)
           VALUES (%s, %s, %s, %s)""",
        subs,
    )
    say(f"  subscriptions      : {len(subs)}")

    # ---------------------------------------------------------- demand alerts
    # Score every out-of-stock product against the threshold so the Admin Demand
    # Log starts consistent with the seeded interest. A few products are left
    # deliberately just below the line, so a live chat session can trip them.
    from . import alerts

    created = 0
    for product in PRODUCTS:
        if product[4] == 0 and alerts.evaluate_product(product[0], reason="seed"):
            created += 1
    say(f"  admin_demand_alerts: {created} pre-existing")


def reset_and_seed(verbose=True):
    """Drop every row (keeping the tables) and re-seed."""
    from .schema import TABLES

    for table in TABLES:
        db.execute(f"DELETE FROM {table}")
    if db.engine() == "sqlite":
        try:
            db.execute("DELETE FROM sqlite_sequence")
        except Exception:
            pass
    seed_all(verbose=verbose)
