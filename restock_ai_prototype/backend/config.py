"""
Central configuration for the Smart Restock AI backend.
Reads from environment variables (.env) with sensible local defaults.
"""
import os
from dotenv import load_dotenv

# Load .env from this file's own directory so it works whether the app is
# launched from backend/ (Flask) or admin_dashboard/ (Streamlit).
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_ENV_PATH)

# ---- MySQL connection ----
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "restock_ai"),
}

# ---- Notification (email) settings ----
# If SMTP creds are not set, notifier.py falls back to a simulated
# notification that is printed to console and appended to
# backend/notifications_log.json — handy for a prototype demo.
SMTP_CONFIG = {
    "host": os.getenv("SMTP_HOST", ""),
    "port": int(os.getenv("SMTP_PORT", "587")),
    "user": os.getenv("SMTP_USER", ""),
    "password": os.getenv("SMTP_PASSWORD", ""),
    "from_email": os.getenv("SMTP_FROM", "restock-alerts@example.com"),
}

# Use SendGrid instead of raw SMTP if an API key is provided
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")

# ---- Business rules ----
HIGH_INTEREST_THRESHOLD = int(os.getenv("HIGH_INTEREST_THRESHOLD", "5"))   # queries+subs before admin alert fires
LOW_STOCK_LOOKAHEAD_DAYS = int(os.getenv("LOW_STOCK_LOOKAHEAD_DAYS", "7")) # flag items predicted to run out within N days
