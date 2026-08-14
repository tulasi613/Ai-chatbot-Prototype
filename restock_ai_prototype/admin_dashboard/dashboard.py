"""
Smart Restock AI - Admin Dashboard (Streamlit)

Run with:
    streamlit run dashboard.py

Covers:
  TASK 3.1 - Current Sales & Stock Intelligence
              (top sellers, inventory levels, stockout frequency)
  TASK 3.2 - Proactive Restock Alerts for Admin
              (sales-velocity based "will run out soon" warnings)
  TASK 3.3 - Future Demand & Sales Predictions
              (search interest + subscriptions + velocity -> demand score)
  TASK 4   - Live Restock Notification Loop
              ("Update Stock Level" button -> notifies subscribed customers)
"""
import sys
import os
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

# Reuse the same backend modules as the Flask API so business logic
# (prediction, notifications) lives in exactly one place.
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))
import db          # noqa: E402
import notifier    # noqa: E402
from config import LOW_STOCK_LOOKAHEAD_DAYS  # noqa: E402

st.set_page_config(page_title="Restock AI — Admin", layout="wide", page_icon="📦")

# ------------------------------------------------------------------
# Styling (kept close to the customer chatbot's dark/amber identity)
# ------------------------------------------------------------------
st.markdown("""
<style>
  .stApp { background-color: #12161c; color: #e7ebf1; }
  section[data-testid="stSidebar"] { background-color: #151b23; }
  div[data-testid="stMetric"] {
      background: #1a2029; border: 1px solid #2a3242;
      border-radius: 12px; padding: 14px 16px;
  }
  .alert-card {
      background: #2a1c1c; border: 1px solid #6b2f2f; border-radius: 10px;
      padding: 12px 14px; margin-bottom: 8px; font-size: 13.5px;
  }
  .alert-card.warn { background: #2c2410; border-color: #6b5a2f; }
</style>
""", unsafe_allow_html=True)

st.title("📦 Restock AI — Admin Dashboard")
st.caption("Sales intelligence, proactive restock alerts, demand forecasting, and live restock actions.")


# ------------------------------------------------------------------
# Data loading (cached briefly so the dashboard stays snappy)
# ------------------------------------------------------------------
@st.cache_data(ttl=30)
def load_products():
    rows = db.query("SELECT * FROM products ORDER BY name")
    return pd.DataFrame(rows)

@st.cache_data(ttl=30)
def load_sales(days=60):
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = db.query(
        "SELECT * FROM sales_log WHERE sale_date >= %s ORDER BY sale_date", (since,)
    )
    return pd.DataFrame(rows)

@st.cache_data(ttl=30)
def load_interest():
    queries = pd.DataFrame(db.query("SELECT * FROM chatbot_query_log"))
    subs = pd.DataFrame(db.query("SELECT * FROM customer_subscriptions"))
    return queries, subs

@st.cache_data(ttl=30)
def load_alerts():
    rows = db.query(
        """SELECT a.*, p.name AS product_name, p.stock_level
           FROM admin_demand_alerts a JOIN products p ON p.product_id = a.product_id
           WHERE a.is_resolved = FALSE ORDER BY a.created_at DESC"""
    )
    return pd.DataFrame(rows)


products_df = load_products()
sales_df = load_sales()
queries_df, subs_df = load_interest()
alerts_df = load_alerts()

if products_df.empty:
    st.error("No products found. Have you run schema.sql and seed_data.sql yet?")
    st.stop()


# ------------------------------------------------------------------
# TOP-LEVEL METRICS
# ------------------------------------------------------------------
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Products", len(products_df))
col2.metric("Out of Stock", int((products_df["stock_level"] == 0).sum()))
col3.metric("Units Sold (60d)", int(sales_df["quantity_sold"].sum()) if not sales_df.empty else 0)
col4.metric("Open Demand Alerts", len(alerts_df))

st.divider()


# ------------------------------------------------------------------
# TASK 3.1 — Current Sales & Stock Intelligence
# ------------------------------------------------------------------
st.header("1. Current Sales & Stock Intelligence")

c1, c2 = st.columns(2)

with c1:
    if not sales_df.empty:
        top_sellers = (
            sales_df.merge(products_df[["product_id", "name"]], on="product_id")
            .groupby("name")["quantity_sold"].sum()
            .sort_values(ascending=False).head(10).reset_index()
        )
        fig = px.bar(top_sellers, x="quantity_sold", y="name", orientation="h",
                     title="Top-Selling Products (last 60 days)",
                     color_discrete_sequence=["#f2a93b"])
        fig.update_layout(yaxis={"categoryorder": "total ascending"},
                           plot_bgcolor="#1a2029", paper_bgcolor="#1a2029",
                           font_color="#e7ebf1", height=400)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No sales history yet.")

with c2:
    fig = px.bar(products_df.sort_values("stock_level"), x="stock_level", y="name",
                 orientation="h", title="Current Inventory Levels",
                 color="stock_level", color_continuous_scale=["#e8637a", "#f2a93b", "#4fc38a"])
    fig.update_layout(plot_bgcolor="#1a2029", paper_bgcolor="#1a2029",
                       font_color="#e7ebf1", height=400, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

# Stockout frequency: how many products are currently at 0, grouped by category
stockouts = products_df[products_df["stock_level"] == 0]
if not stockouts.empty:
    freq = stockouts.groupby("category").size().reset_index(name="stockout_count")
    fig = px.bar(freq, x="category", y="stockout_count", title="Stockout Frequency by Category (current)",
                 color_discrete_sequence=["#e8637a"])
    fig.update_layout(plot_bgcolor="#1a2029", paper_bgcolor="#1a2029",
                       font_color="#e7ebf1", height=320)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.success("No products are currently out of stock.")

st.divider()


# ------------------------------------------------------------------
# TASK 3.2 — Proactive Restock Alerts for Admin
# ------------------------------------------------------------------
st.header("2. Proactive Restock Alerts")
st.caption(f"Flags in-stock items predicted to run out within {LOW_STOCK_LOOKAHEAD_DAYS} days, based on recent sales velocity.")

def compute_velocity(pid, days=14):
    since = (date.today() - timedelta(days=days)).isoformat()
    sub = sales_df[(sales_df["product_id"] == pid) & (sales_df["sale_date"].astype(str) >= since)]
    total = sub["quantity_sold"].sum() if not sub.empty else 0
    return round(total / days, 2)

rows = []
for _, p in products_df.iterrows():
    if p["stock_level"] <= 0:
        continue
    v = compute_velocity(p["product_id"])
    days_left = round(p["stock_level"] / v, 1) if v > 0 else None
    if days_left is not None and days_left <= LOW_STOCK_LOOKAHEAD_DAYS:
        rows.append({
            "product_id": p["product_id"],
            "Product": p["name"],
            "Stock": p["stock_level"],
            "Daily Velocity": v,
            "Est. Days Until Stockout": days_left,
        })

if rows:
    forecast_df = pd.DataFrame(rows).sort_values("Est. Days Until Stockout")
    for _, r in forecast_df.iterrows():
        st.markdown(
            f"""<div class="alert-card warn">⚠️ <b>{r['Product']}</b> — {r['Stock']} units left,
            selling ~{r['Daily Velocity']}/day → projected stockout in
            <b>{r['Est. Days Until Stockout']} days</b>. Reorder now.</div>""",
            unsafe_allow_html=True,
        )
else:
    st.success("No fast-selling items are projected to run out soon.")

# High-interest OOS alerts (fed by the chatbot backend)
if not alerts_df.empty:
    st.subheader("High Customer Interest on Out-of-Stock Items")
    for _, a in alerts_df.iterrows():
        st.markdown(
            f"""<div class="alert-card">🔥 <b>{a['product_name']}</b> — {a['alert_message']}</div>""",
            unsafe_allow_html=True,
        )

st.divider()


# ------------------------------------------------------------------
# TASK 3.3 — Future Demand & Sales Predictions
# ------------------------------------------------------------------
st.header("3. Future Demand Predictions")
st.caption("Blends chatbot search interest, active subscriptions, and recent sales velocity into a single demand score.")

demand_rows = []
for _, p in products_df.iterrows():
    pid = p["product_id"]
    q_count = len(queries_df[queries_df["product_id"] == pid]) if not queries_df.empty else 0
    s_count = len(subs_df[subs_df["product_id"] == pid]) if not subs_df.empty else 0
    velocity = compute_velocity(pid, days=30)
    # normalize/weight the three signals into one 0-100 demand score
    demand_score = round(min(100, q_count * 4 + s_count * 6 + velocity * 10), 1)
    demand_rows.append({
        "Product": p["name"], "Category": p["category"],
        "Search Interest": q_count, "Subscriptions": s_count,
        "Sales Velocity (u/day)": velocity, "Demand Score": demand_score,
    })

demand_df = pd.DataFrame(demand_rows).sort_values("Demand Score", ascending=False).head(12)
fig = px.bar(demand_df, x="Demand Score", y="Product", orientation="h",
             color="Demand Score", color_continuous_scale=["#2a3242", "#f2a93b"],
             title="Predicted Demand Score — Next Period", hover_data=["Search Interest", "Subscriptions", "Sales Velocity (u/day)"])
fig.update_layout(yaxis={"categoryorder": "total ascending"},
                   plot_bgcolor="#1a2029", paper_bgcolor="#1a2029",
                   font_color="#e7ebf1", height=450, showlegend=False)
st.plotly_chart(fig, use_container_width=True)

st.divider()


# ------------------------------------------------------------------
# TASK 4 — Live Restock Notification Loop
# ------------------------------------------------------------------
st.header("4. Update Stock Level / Restock Item")
st.caption("Increasing stock on an out-of-stock item automatically notifies every customer subscribed to it.")

with st.form("restock_form"):
    options = {f'{row["name"]}  (current: {row["stock_level"]})': row["product_id"]
               for _, row in products_df.iterrows()}
    choice = st.selectbox("Product", list(options.keys()))
    new_level = st.number_input("New stock level", min_value=0, value=20, step=1)
    submitted = st.form_submit_button("🔄 Update Stock & Notify Subscribers")

if submitted:
    pid = options[choice]
    product = db.query("SELECT * FROM products WHERE product_id = %s", (pid,), fetchone=True)
    was_oos = product["stock_level"] == 0

    db.execute("UPDATE products SET stock_level = %s WHERE product_id = %s", (new_level, pid))

    notified = []
    if was_oos and new_level > 0:
        subscribers = db.query(
            "SELECT * FROM customer_subscriptions WHERE product_id = %s AND notified = FALSE", (pid,)
        )
        for sub in subscribers:
            ok = notifier.send_restock_notification(
                sub["customer_email"], sub["customer_phone"], product["name"], new_level
            )
            if ok:
                db.execute(
                    "UPDATE customer_subscriptions SET notified = TRUE, notified_at = NOW() WHERE subscription_id = %s",
                    (sub["subscription_id"],),
                )
                notified.append(sub["customer_email"] or sub["customer_phone"])
        db.execute(
            """UPDATE admin_demand_alerts SET is_resolved = TRUE
               WHERE product_id = %s AND alert_type = 'high_interest_oos'""",
            (pid,),
        )

    st.success(f"Stock for '{product['name']}' updated to {new_level} units.")
    if notified:
        st.info(f"📧 Notified {len(notified)} subscribed customer(s): {', '.join(notified)}")
    elif was_oos:
        st.caption("No subscribers were waiting on this item.")

    st.cache_data.clear()
    st.rerun()

# Notification log preview
log_path = os.path.join(os.path.dirname(__file__), "..", "backend", "notifications_log.json")
if os.path.exists(log_path):
    with st.expander("📜 Recent notification log"):
        log_df = pd.read_json(log_path)
        st.dataframe(log_df.tail(20), use_container_width=True)
