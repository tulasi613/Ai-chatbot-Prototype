# Task 2 — Customer-Facing AI Chatbot

A restock assistant that answers *"when is this coming back?"*, recommends
in-stock alternatives, captures the customer's contact details for a restock
alert, and escalates high-demand items to the admin team — all against the
`restock_ai` MySQL schema.

```
┌──────────────────────────┐        ┌────────────────────────────┐
│  Chat (customer)         │        │  Live system view (admin)  │
│  ─────────────────       │        │  ────────────────────      │
│  1. restock prediction   │  ───▶  │  admin_demand_alerts       │
│  2. alternatives + match │        │  customer_subscriptions    │
│  3. notify-me capture    │        │  live demand scores        │
└──────────────────────────┘        └────────────────────────────┘
```

---

## Run it (30 seconds, nothing to install)

```bash
cd task2_chatbot
python3 run.py
```

That's it. It creates the schema, seeds 24 products with 60 days of sales
history, starts the server, and opens <http://127.0.0.1:5055> in your browser.

Want to watch the whole flow play itself out? Open:

```
http://127.0.0.1:5055/?demo=1
```

Useful flags: `--reset` (rebuild the demo data), `--port 8080`, `--no-browser`.

> **Why it runs with no setup:** by default the app uses a local SQLite file
> that mirrors the MySQL schema exactly. Point it at MySQL with one env var
> (below) and the same code runs unchanged.

### Run it against real MySQL

```bash
cp .env.example .env         # then set DB_ENGINE=mysql and your DB_PASSWORD
pip install mysql-connector-python
python3 -m app.init_db --reset
python3 run.py
```

`database/schema_mysql.sql` is the canonical DDL if you'd rather create the
tables by hand (`mysql -u root -p < database/schema_mysql.sql`).

---

## The four required capabilities

### 1. Predict availability

Ask *"When will the Smart Fitness Watch be back?"* and the bot replies with a
window and a confidence score:

> **Expected back in 4–6 days with 92.8% confidence**

The model ([app/predictor.py](app/predictor.py)) is a transparent heuristic
built from the schema's own data — no black box, and every number is explained
in the *"How this prediction was made"* drawer:

| Signal | Source | Effect |
|---|---|---|
| Supplier lead time | `suppliers.avg_lead_time_days` | sets the centre of the window |
| Delivery cadence | `suppliers.last_delivery_date` | shaves up to 25% off when a shipment is already due |
| Sales velocity | `sales_log` (30-day) | adds up to 3 days of handling time under heavy demand |
| Supplier reliability | `suppliers.reliability_score` | widens/narrows the window (± spread) |
| Demand volatility | 14-day vs prior 14-day trend | −4 confidence points when swings exceed 40% |
| History depth | days of sales on record | up to +5 confidence points |

Confidence is clamped to a defensible 45–97%.

### 2. Alternative recommendations

Every product becomes a **TF-IDF vector** built from its name, category and JSON
attributes; candidates are ranked by **cosine similarity**
([app/similarity.py](app/similarity.py)):

```
match = 0.50 · cosine(tfidf) + 0.25 · jaccard(attributes) + 0.25 · price closeness
        + 0.12 same-category bonus
```

Only in-stock products are offered, and each result explains itself
("Same category · Shares black, gps, heart rate · $20.00 cheaper"). Hover a card
to see the raw breakdown. Pure Python — no numpy or scikit-learn needed.

### 3. Customer subscription trigger

The bot asks for an email or phone **inside the chat**, validates it, and writes
to `customer_subscriptions`. Free text works too — *"ping me at
priya@example.com"* is parsed straight into a subscription. Repeat signups are
de-duplicated instead of creating a second row.

The confirmation card shows the real row id, so you can verify it:

```sql
SELECT * FROM customer_subscriptions ORDER BY subscription_id DESC LIMIT 5;
```

### 4. Admin demand alert

Every chat turn is logged to `chatbot_query_log`. Interest is scored as:

```
demand_score = 1.0 × chat queries (last 21 days) + 3.0 × subscriptions
```

When an **out-of-stock** product crosses the threshold (default `6`), a row is
written to `admin_demand_alerts` and it appears instantly in the right-hand
panel with a toast. Crossing again *updates* the existing alert rather than
spamming duplicates, and restocking the item resolves it.

The seed data deliberately leaves **Smart Fitness Watch at 4/6**, so two
questions — or one subscription — trips a live alert while you watch.

---

## What you'll see

| Panel | Shows |
|---|---|
| **Chat** | prediction card with confidence ring, ranked alternatives, inline subscribe form |
| **Demand log** | open `admin_demand_alerts` + a live demand meter per out-of-stock product |
| **Subscriptions** | every captured contact and whether they've been notified |
| **Restock** | put stock back → every subscriber is notified and the alert resolves |

The **Restock** tab closes the loop: pick the product you just subscribed to,
set a stock level, and watch the notifications fire and the alert clear.

---

## Try these

```
When will the Smart Fitness Watch be back in stock?
How did you predict that?
Show me something similar to the running jacket
Notify me at priya.sharma@example.com
What else is out of stock?
vitamin c serum                 ← ambiguous on purpose: the bot asks which one
how much is the electric kettle
```

---

## Project layout

```
task2_chatbot/
├── run.py                  one-command launcher
├── app/
│   ├── config.py           env-driven settings
│   ├── db.py               dual-engine adapter (MySQL / SQLite, one SQL dialect)
│   ├── schema.py           DDL for both engines
│   ├── seed.py             24 products, 60 days of sales history
│   ├── init_db.py          python -m app.init_db [--reset]
│   ├── nlu.py              intent detection + product resolution
│   ├── predictor.py        FEATURE 1 — restock ETA + confidence
│   ├── similarity.py       FEATURE 2 — TF-IDF vector matching
│   ├── subscriptions.py    FEATURE 3 — contact capture + notification sweep
│   ├── alerts.py           FEATURE 4 — demand scoring + admin log
│   ├── chatbot.py          conversation orchestration
│   ├── api.py              routes (framework-agnostic)
│   └── server.py           Flask if available, else http.server
├── database/schema_mysql.sql
├── ui/                     index.html · styles.css · app.js  (no CDN, no build)
└── tests/test_flow.py      75 end-to-end checks
```

---

## API

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/chat` | conversational entry point — all four features |
| POST | `/api/chat/availability` | restock prediction for a product |
| POST | `/api/chat/alternatives` | ranked in-stock alternatives |
| POST | `/api/chat/subscribe` | save a restock subscription |
| GET | `/api/admin/alerts` | the Admin Demand Log |
| GET | `/api/admin/demand` | live demand score per out-of-stock product |
| GET | `/api/admin/subscriptions` | captured contacts |
| POST | `/api/admin/restock` | set stock + notify everyone waiting |
| POST | `/api/admin/reset` | rebuild the demo data |
| GET | `/api/health`, `/api/products`, `/api/products/<id>` | supporting |

```bash
curl -X POST localhost:5055/api/chat/availability \
     -H 'Content-Type: application/json' -d '{"product_id": 4}'

curl -X POST localhost:5055/api/chat \
     -H 'Content-Type: application/json' \
     -d '{"message": "when will the smart fitness watch be back?"}'
```

`/api/chat` returns a block-structured turn (`text`, `product`, `prediction`,
`alternatives`, `subscribe_form`, `subscription_confirmed`, `catalog`) plus
`quick_replies` and `events`, so any front end can render it.

---

## Tests

```bash
python3 tests/test_flow.py
```

75 checks covering the prediction model, similarity ranking, subscription
validation and de-duplication, alert threshold behaviour, the restock
notification loop, intent classification, and the full REST surface. Runs
against a throwaway database, so your demo data is untouched.

---

## Notes

- Notifications are **simulated** — the message body is returned to the UI and
  the row is marked notified. Swap `subscriptions.notify_waiting()` for SMTP or
  an SMS provider to go live.
- Sales history is generated relative to today with a fixed seed, so the
  prediction windows always have data no matter when you run it.
- Sessions are held in memory (`chatbot._SESSIONS`) with a 2-hour TTL; move
  them to Redis for a multi-process deployment.
