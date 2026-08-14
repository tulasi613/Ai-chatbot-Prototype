"""
Feature 1 - Predict Availability.

A transparent, explainable restock model built from the data the schema already
stores: supplier lead time, supplier reliability, delivery cadence and the
product's own sales history.

    predict_restock_eta(1)
    -> {"min_days": 4, "max_days": 7, "confidence_pct": 92.1, ...}

Every number the customer sees comes back with the factor that produced it, so
the same payload powers both the chat reply and the "how we predicted this"
panel in the UI.
"""
from datetime import date, datetime, timedelta

from . import db


# ------------------------------------------------------------------ demand signals
def sales_velocity(product_id, days=30):
    """Average units sold per day over the trailing window."""
    since = (date.today() - timedelta(days=days)).isoformat()
    row = db.query(
        """SELECT COALESCE(SUM(quantity_sold), 0) AS total,
                  COUNT(*) AS day_count
           FROM sales_log
           WHERE product_id = %s AND sale_date >= %s""",
        (product_id, since),
        fetchone=True,
    )
    total = float(row["total"] or 0)
    return round(total / days, 2), int(row["day_count"] or 0)


def demand_trend(product_id):
    """Recent 14 days vs the 14 before that -> % change in units sold."""
    recent, _ = sales_velocity(product_id, days=14)
    since = (date.today() - timedelta(days=28)).isoformat()
    until = (date.today() - timedelta(days=14)).isoformat()
    row = db.query(
        """SELECT COALESCE(SUM(quantity_sold), 0) AS total
           FROM sales_log
           WHERE product_id = %s AND sale_date >= %s AND sale_date < %s""",
        (product_id, since, until),
        fetchone=True,
    )
    previous = float(row["total"] or 0) / 14
    if previous <= 0:
        return 0.0
    return round((recent - previous) / previous * 100, 1)


def days_of_cover(product_id, stock_level):
    """How long current stock lasts at the current selling pace."""
    velocity, _ = sales_velocity(product_id, days=14)
    if velocity <= 0:
        return None
    return round(stock_level / velocity, 1)


# ------------------------------------------------------------------ the model
def predict_restock_eta(product_id):
    product = db.query(
        "SELECT * FROM products WHERE product_id = %s", (product_id,), fetchone=True
    )
    if not product:
        return None

    supplier = None
    if product.get("supplier_id"):
        supplier = db.query(
            "SELECT * FROM suppliers WHERE supplier_id = %s",
            (product["supplier_id"],),
            fetchone=True,
        )

    velocity, active_days = sales_velocity(product_id, days=30)
    trend = demand_trend(product_id)
    factors = []

    if not supplier:
        return {
            "product_id": product_id,
            "min_days": 7,
            "max_days": 14,
            "confidence_pct": 50.0,
            "supplier_name": "Unassigned supplier",
            "eta_from": (date.today() + timedelta(days=7)).isoformat(),
            "eta_to": (date.today() + timedelta(days=14)).isoformat(),
            "sales_velocity": velocity,
            "demand_trend_pct": trend,
            "factors": [{
                "label": "No supplier on file",
                "detail": "Falling back to the 7-14 day catalogue-wide average.",
                "impact": "negative",
            }],
            "explanation": "No supplier is linked to this product, so we used a generic estimate.",
        }

    base_lead = int(supplier["avg_lead_time_days"])
    reliability = float(supplier["reliability_score"]) / 100.0

    factors.append({
        "label": f"{supplier['supplier_name']} lead time",
        "detail": f"Averages {base_lead} days from purchase order to delivery.",
        "impact": "neutral",
        "value": f"{base_lead} days",
    })

    # 1) Where we are in the supplier's delivery cycle. A supplier that last
    #    delivered a full cycle ago is likely mid-shipment already.
    cycle_credit = 0.0
    if supplier.get("last_delivery_date"):
        last = _parse_date(supplier["last_delivery_date"])
        if last:
            days_since = max(0, (date.today() - last).days)
            cycle_position = min(days_since / max(base_lead, 1), 1.0)
            cycle_credit = base_lead * 0.25 * cycle_position
            if cycle_position >= 0.8:
                factors.append({
                    "label": "Restock cycle nearly due",
                    "detail": f"Last delivery was {days_since} days ago — a shipment is due imminently.",
                    "impact": "positive",
                    "value": f"-{cycle_credit:.1f} days",
                })

    # 2) High sell-through means the incoming batch has to be bigger, which
    #    historically adds a little handling time.
    demand_pressure = min(3.0, velocity * 0.6)
    if demand_pressure >= 0.5:
        factors.append({
            "label": "High demand pressure",
            "detail": f"Selling {velocity} units/day over the last 30 days"
                      + (f", trending {trend:+.0f}%." if trend else "."),
            "impact": "negative",
            "value": f"+{demand_pressure:.1f} days",
        })

    centre = max(1.0, base_lead - cycle_credit + demand_pressure)

    # 3) Unreliable suppliers get a wider window, not a later one.
    spread = max(1.0, centre * (1 - reliability) * 2.2)
    min_days = max(1, int(round(centre - spread)))
    max_days = max(min_days + 1, int(round(centre + spread)))

    factors.append({
        "label": "Supplier reliability",
        "detail": f"{supplier['reliability_score']}% of past deliveries arrived on time.",
        "impact": "positive" if reliability >= 0.92 else "neutral",
        "value": f"±{spread:.1f} days",
    })

    # 4) Confidence: reliability, tempered by demand volatility and how much
    #    sales history we actually have to reason about.
    confidence = reliability * 100
    confidence -= min(8.0, velocity * 1.5)
    if abs(trend) > 40:
        confidence -= 4
        factors.append({
            "label": "Volatile demand",
            "detail": f"Sales moved {trend:+.0f}% versus the previous fortnight.",
            "impact": "negative",
            "value": "-4 pts confidence",
        })
    history_bonus = min(5.0, active_days / 6.0)
    confidence += history_bonus
    factors.append({
        "label": "Sales history depth",
        "detail": f"{active_days} days of recorded sales in the last 30 days.",
        "impact": "positive" if active_days >= 18 else "neutral",
        "value": f"+{history_bonus:.1f} pts confidence",
    })
    confidence = round(max(45.0, min(97.0, confidence)), 1)

    return {
        "product_id": product_id,
        "min_days": min_days,
        "max_days": max_days,
        "confidence_pct": confidence,
        "supplier_name": supplier["supplier_name"],
        "supplier_reliability": float(supplier["reliability_score"]),
        "eta_from": (date.today() + timedelta(days=min_days)).isoformat(),
        "eta_to": (date.today() + timedelta(days=max_days)).isoformat(),
        "sales_velocity": velocity,
        "demand_trend_pct": trend,
        "factors": factors,
        "explanation": (
            f"Based on {supplier['supplier_name']}'s {base_lead}-day average lead time "
            f"and a {supplier['reliability_score']}% on-time delivery record."
        ),
    }


def _parse_date(value):
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value)[:19], fmt).date()
        except ValueError:
            continue
    return None
