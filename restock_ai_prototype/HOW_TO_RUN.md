# How to Run — Smart Restock AI Prototype

Step-by-step guide to get the database, chatbot API, chatbot UI, and admin
dashboard running locally from this zip.

## Prerequisites

Install these first if you don't already have them:

| Tool | Version | Check with |
|---|---|---|
| Python | 3.10+ | `python3 --version` |
| MySQL Server | 8.0+ | `mysql --version` |
| pip | any recent | `pip3 --version` |

**Install MySQL if needed:**
- macOS: `brew install mysql && brew services start mysql`
- Windows: download the installer from https://dev.mysql.com/downloads/installer/
- Ubuntu/Debian: `sudo apt install mysql-server && sudo systemctl start mysql`

---

## Step 1 — Unzip the project

```bash
unzip restock_ai_prototype.zip
cd restock_ai_prototype
```

You should see: `database/`, `backend/`, `chatbot_ui/`, `admin_dashboard/`, `README.md`.

---

## Step 2 — Create and seed the MySQL database

From the project root:

```bash
mysql -u root -p < database/schema.sql
mysql -u root -p < database/seed_data.sql
```

Enter your MySQL root password when prompted. This creates a `restock_ai`
database with 17 sample products, 5 suppliers, ~45 days of sales history,
sample subscriptions, and chatbot query logs.

**Verify it worked:**
```bash
mysql -u root -p -e "USE restock_ai; SELECT COUNT(*) FROM products;"
```
You should see `17`.

---

## Step 3 — Configure your environment variables

```bash
cd backend
cp .env.example .env
```

Open `.env` in any text editor and set your MySQL password:

```
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_actual_mysql_password
DB_NAME=restock_ai
```

Leave the `SMTP_*` / `SENDGRID_API_KEY` fields blank — restock notifications
will run in **simulated mode** (printed to console + logged to
`backend/notifications_log.json`), so no email service is required to demo Task 4.

---

## Step 4 — Install Python dependencies

It's best to use a virtual environment so packages don't clash with anything else on your machine:

```bash
# from the project root
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r backend/requirements.txt
pip install -r admin_dashboard/requirements.txt
```

---

## Step 5 — Start the chatbot backend (Flask API)

```bash
cd backend
python app.py
```

You should see it running on `http://localhost:5000`. Leave this terminal open.

**Quick test** (in a second terminal):
```bash
curl http://localhost:5000/api/products
```
This should return a JSON list of 17 products.

---

## Step 6 — Open the chatbot UI

Just open the file directly in your browser:

```bash
# macOS
open chatbot_ui/index.html
# Windows
start chatbot_ui/index.html
# Linux
xdg-open chatbot_ui/index.html
```

Tap a product chip (or type a name like "headphones") to see:
1. **Availability** — restock ETA with confidence %
2. **Alternatives** — 2–3 in-stock matches with match scores
3. **Subscribe** — enter an email/phone to save a restock subscription to MySQL

> The backend from Step 5 must be running for this page to work — it calls `http://localhost:5000`.

---

## Step 7 — Start the admin dashboard (Streamlit)

Open a **new terminal** (keep the Flask server running), then:

```bash
cd restock_ai_prototype
source venv/bin/activate        # Windows: venv\Scripts\activate
cd admin_dashboard
streamlit run dashboard.py
```

This opens automatically in your browser at `http://localhost:8501`, showing:
1. Sales & stock intelligence (top sellers, inventory levels, stockout frequency)
2. Proactive restock alerts (low-stock warnings + high-interest OOS alerts)
3. Future demand predictions (blended demand score chart)
4. **Live restock action** — pick a product, set a new stock level, click
   **"Update Stock & Notify Subscribers"**

---

## Step 8 — Try the full end-to-end flow

1. In the **chatbot UI**, ask about an out-of-stock item (e.g. "Smart Fitness Watch") and subscribe with your email.
2. In the **admin dashboard**, scroll to section 4, select that same product, set stock to something like `20`, and click the update button.
3. Watch it notify your subscription — check `backend/notifications_log.json` to see the logged (simulated) notification.
4. Refresh the dashboard — the high-interest alert for that product should now be resolved, and the stock chart updates.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Access denied for user 'root'@'localhost'` | Double-check `DB_PASSWORD` in `.env` matches your MySQL root password. |
| `Can't connect to MySQL server` | Make sure MySQL is running: `brew services start mysql` (macOS) or `sudo systemctl start mysql` (Linux). |
| `ModuleNotFoundError: No module named 'flask'` etc. | You likely forgot to activate the virtual environment, or skipped `pip install -r requirements.txt`. |
| Chatbot UI shows "Couldn't reach the backend" | Confirm `python app.py` is still running in a terminal and there's no firewall blocking `localhost:5000`. |
| `Address already in use` on port 5000 or 8501 | Another process is using that port — stop it, or change the port (`app.run(port=5001)` in `app.py`, or `streamlit run dashboard.py --server.port 8502`). |
| Dashboard shows "No products found" | The schema/seed SQL didn't run successfully — repeat Step 2 and check for errors in the terminal output. |

---

## Stopping everything

- Flask backend: `Ctrl+C` in its terminal
- Streamlit dashboard: `Ctrl+C` in its terminal
- Deactivate the virtual environment: `deactivate`
