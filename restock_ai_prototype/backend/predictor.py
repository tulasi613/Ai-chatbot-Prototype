"""
Lightweight prediction models for the chatbot.

1. predict_restock_eta(product_id)
   Combines supplier lead time + historical delivery reliability +
   recent sales velocity into an estimated restock window and a
   confidence percentage. No external ML library needed for the
   prototype — this is a transparent, explainable heuristic model
   that can later be swapped for a trained regressor.

2. find_alternatives(product_id, limit=3)
   Feature/category matching: filters in-stock products in the same
   category, then scores similarity using Jaccard similarity over
   product attributes + normalized price closeness.

3. compute_sales_velocity(product_id, days=14)
   Units sold per day, used both by the chatbot and the admin
   dashboard's low-stock forecasting panel.
"""
import json
from datetime import date, timedelta
import db


# ------------------------------------------------------------------
# 1. Restock ETA prediction
# ------------------------------------------------------------------
def compute_sales_velocity(product_id, days=14):
    """Average units sold per day over the trailing `days` window."""
    since = (date.today() - timedelta(days=days)).isoformat()
    row = db.query(
        """SELECT COALESCE(SUM(quantity_sold), 0) AS total
           FROM sales_log
           WHERE product_id = %s AND sale_date >= %s""",
        (product_id, since),
        fetchone=True,
    )
    total = float(row["total"]) if row else 0.0
    return round(total / days, 2)


def predict_restock_eta(product_id):
    """
    Returns a dict:
      {
        "min_days": int,
        "max_days": int,
        "confidence_pct": float,
        "supplier_name": str,
        "explanation": str
      }
    or None if the product/supplier can't be found.
    """
    product = db.query(
        "SELECT * FROM products WHERE product_id = %s", (product_id,), fetchone=True
    )
    if not product:
        return None

    supplier = db.query(
        "SELECT * FROM suppliers WHERE supplier_id = %s",
        (product["supplier_id"],),
        fetchone=True,
    )
    if not supplier:
        # No supplier on file -> fall back to a generic conservative estimate
        return {
            "min_days": 7,
            "max_days": 14,
            "confidence_pct": 50.0,
            "supplier_name": "Unknown",
            "explanation": "No supplier data on file; using a generic estimate.",
        }

    base_lead = supplier["avg_lead_time_days"]
    reliability = float(supplier["reliability_score"]) / 100.0  # e.g. 0.92

    # Less reliable suppliers => wider uncertainty window
    variance_days = max(1, round(base_lead * (1 - reliability) * 2))
    min_days = max(1, base_lead - variance_days)
    max_days = base_lead + variance_days

    # High recent demand on a popular item nudges confidence down slightly
    # (higher chance of the new shipment selling out again fast / supplier
    # struggling to keep pace), and rewards suppliers with strong reliability.
    velocity = compute_sales_velocity(product_id, days=30)
    demand_penalty = min(velocity * 1.5, 10)  # cap penalty at 10 pts
    confidence_pct = round(max(40.0, reliability * 100 - demand_penalty), 1)

    explanation = (
        f"Based on {supplier['supplier_name']}'s average lead time of "
        f"{base_lead} days and a historical on-time delivery rate of "
        f"{supplier['reliability_score']}%."
    )

    return {
        "min_days": min_days,
        "max_days": max_days,
        "confidence_pct": confidence_pct,
        "supplier_name": supplier["supplier_name"],
        "explanation": explanation,
    }


# ------------------------------------------------------------------
# 2. Alternative product recommendation
# ------------------------------------------------------------------
def _attr_similarity(attrs_a, attrs_b):
    """Jaccard similarity over key:value pairs of two attribute dicts."""
    if not attrs_a or not attrs_b:
        return 0.0
    set_a = {f"{k}={v}" for k, v in attrs_a.items()}
    set_b = {f"{k}={v}" for k, v in attrs_b.items()}
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


def _price_similarity(price_a, price_b):
    price_a, price_b = float(price_a), float(price_b)
    if max(price_a, price_b) == 0:
        return 1.0
    return 1 - abs(price_a - price_b) / max(price_a, price_b)


def find_alternatives(product_id, limit=3):
    target = db.query(
        "SELECT * FROM products WHERE product_id = %s", (product_id,), fetchone=True
    )
    if not target:
        return []

    candidates = db.query(
        """SELECT * FROM products
           WHERE category = %s AND product_id != %s AND stock_level > 0""",
        (target["category"], product_id),
    )

    target_attrs = json.loads(target["attributes"]) if target["attributes"] else {}

    scored = []
    for c in candidates:
        c_attrs = json.loads(c["attributes"]) if c["attributes"] else {}
        attr_sim = _attr_similarity(target_attrs, c_attrs)
        price_sim = _price_similarity(target["price"], c["price"])
        match_score = round((attr_sim * 0.6 + price_sim * 0.4) * 100, 1)
        scored.append({
            "product_id": c["product_id"],
            "name": c["name"],
            "category": c["category"],
            "price": float(c["price"]),
            "stock_level": c["stock_level"],
            "image_url": c["image_url"],
            "match_score": match_score,
        })

    scored.sort(key=lambda x: x["match_score"], reverse=True)
    return scored[:limit]
