"""
Configuration for the Smart Restock AI chatbot.

Everything is env-driven with sane defaults so the demo runs with zero setup:
  * DB_ENGINE=sqlite  (default) -> a local file DB, no server needed
  * DB_ENGINE=mysql             -> the real MySQL schema in database/schema_mysql.sql
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv():
    """Minimal .env loader (avoids a python-dotenv dependency)."""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# ---------------------------------------------------------------- database
DB_ENGINE = os.getenv("DB_ENGINE", "sqlite").lower()

MYSQL_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "restock_ai"),
}

SQLITE_PATH = Path(os.getenv("SQLITE_PATH", BASE_DIR / "data" / "restock_ai.db"))

# ---------------------------------------------------------------- server
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "5055"))

# ---------------------------------------------------------------- business rules
# Interest score at which an out-of-stock product is escalated to the Admin Demand Log.
HIGH_INTEREST_THRESHOLD = int(os.getenv("HIGH_INTEREST_THRESHOLD", "6"))

# Weight of each interest signal when computing the demand score.
WEIGHT_QUERY = float(os.getenv("WEIGHT_QUERY", "1.0"))
WEIGHT_SUBSCRIPTION = float(os.getenv("WEIGHT_SUBSCRIPTION", "3.0"))

# Only interest recorded in the trailing N days counts toward an alert.
INTEREST_WINDOW_DAYS = int(os.getenv("INTEREST_WINDOW_DAYS", "21"))

# How many alternatives the chatbot offers.
MAX_ALTERNATIVES = int(os.getenv("MAX_ALTERNATIVES", "3"))
