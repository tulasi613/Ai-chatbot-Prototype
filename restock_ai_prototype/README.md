# Smart Restock AI — Prototype

An AI-assisted retail prototype: a customer-facing chatbot that predicts restock timing,
recommends alternatives, and captures restock subscriptions — plus an admin dashboard
with sales intelligence, proactive low-stock alerts, demand forecasting, and a live
"update stock → notify customers" loop.

```
restock_ai_prototype/
├── database/
│   ├── schema.sql          # MySQL table definitions
│   └── seed_data.sql       # 17 sample products, suppliers, 45 days of sales, subscriptions
├── backend/
│   ├── app.py               # Flask API — the 3 core chatbot endpoints + admin/restock
│   ├── config.py            # DB / SMTP / SendGrid / business-rule settings (.env driven)
│   ├── db.py                 # MySQL connection pool + query/execute helpers
│   ├── predictor.py         # Restock-ETA model + alternative-product matching
│   ├── notifier.py          # Email notifications (SendGrid / SMTP / simulated)
│   ├── requirements.txt
│   └── .env.example         # copy to .env and fill in your MySQL credentials
├── chatbot_ui/
│   └── index.html            # Single-file chat widget (vanilla HTML/CSS/JS)
└── admin_dashboard/
    ├── dashboard.py          # Streamlit admin dashboard (Tasks 3 & 4)
    └── requirements.txt
```

## 1. Set up MySQL

```bash
mysql -u root -p < database/schema.sql
mysql -u root -p < database/seed_data.sql
```

This creates the `restock_ai` database with:
- **products** — 17 sample products across 5 categories (several seeded at 0 stock)
- **suppliers** — 5 suppliers with average lead times & historical reliability %
- **sales_log** — ~45 days of simulated sales history per product
- **customer_subscriptions** — sample "notify me" sign-ups on out-of-stock items
- **chatbot_query_log** — simulated prior chatbot interest
- **admin_demand_alerts** — populated automatically at runtime

## 2. Configure environment

```bash
cd backend
cp .env.example .env
# edit .env with your MySQL password (and optionally SMTP/SendGrid creds)
```

If you leave the SMTP/SendGrid fields blank, the notification system runs in
**simulated mode**: it prints notifications to the console and logs them to
`backend/notifications_log.json`, so Task 4 is fully demoable with zero external services.

## 3. Run the backend (chatbot API)

```bash
cd backend
pip install -r requirements.txt
python app.py
```

Starts the Flask API on `http://localhost:5000`.

### The 3 core Task 2 endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/chat/availability` | POST `{product_id}` | Predicts restock ETA (min–max days + confidence %) using supplier lead time, delivery reliability, and sales velocity. Logs interest & may trigger an admin demand alert. |
| `/api/chat/alternatives` | POST `{product_id}` | Returns 2–3 in-stock alternatives in the same category, ranked by a match score (attribute similarity + price closeness). |
| `/api/chat/subscribe` | POST `{product_id, email, phone}` | Saves a restock subscription to MySQL and re-checks the admin demand alert threshold. |

Supporting endpoints: `GET /api/products` (search/list), `GET /api/admin/alerts`,
`POST /api/admin/restock` (Task 4 trigger, also used by the dashboard directly).

## 4. Open the chatbot UI

Just open `chatbot_ui/index.html` in a browser (or serve it with any static
server). It talks to the Flask API at `http://localhost:5000`. Try tapping an
out-of-stock product chip — you'll see the availability prediction,
alternatives, and a "Notify Me" subscribe form chained together automatically.

## 5. Run the admin dashboard

```bash
cd admin_dashboard
pip install -r requirements.txt
streamlit run dashboard.py
```

Covers:
1. **Sales & Stock Intelligence** — top sellers, current inventory levels, stockout frequency by category
2. **Proactive Restock Alerts** — flags in-stock items projected to sell out within N days based on velocity, plus the high-interest OOS alerts fired by the chatbot
3. **Future Demand Predictions** — a blended demand score from search interest + subscriptions + sales velocity
4. **Live Restock Loop (Task 4)** — pick a product, set its new stock level, and click
   **"Update Stock & Notify Subscribers."** If the item was out of stock and is now
   available, every subscribed customer gets an (email or simulated) notification,
   and the corresponding admin alert is auto-resolved.

## How the prediction logic works (transparent, explainable heuristics)

- **Restock ETA** = supplier's average lead time ± an uncertainty window that widens
  as historical reliability drops, with a small confidence penalty for high current
  sales velocity (popular items are more likely to sell out again quickly).
- **Alternative match score** = `0.6 × attribute Jaccard similarity + 0.4 × price closeness`,
  restricted to in-stock items in the same category.
- **Demand score** (dashboard) = weighted blend of chatbot search interest, active
  subscriptions, and 30-day sales velocity.

These are intentionally simple, explainable models suited to a prototype — swap
`predictor.py`'s functions for a trained ML model later without touching the API layer.

## Notes

- `HIGH_INTEREST_THRESHOLD` (default 5) and `LOW_STOCK_LOOKAHEAD_DAYS` (default 7) are
  configurable in `.env`.
- The dashboard and Flask API both import the same `db.py` / `predictor.py` /
  `notifier.py` modules, so business logic lives in one place.
