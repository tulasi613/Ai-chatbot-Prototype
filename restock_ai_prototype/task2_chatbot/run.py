#!/usr/bin/env python3
"""
One-command launcher.

    python3 run.py                 # init db if needed, start the server, open the UI
    python3 run.py --reset         # rebuild the demo data first
    python3 run.py --port 8080     # different port
    python3 run.py --no-browser    # don't open a browser window

Requires nothing but Python 3.10+. Set DB_ENGINE=mysql in .env to run the same
app against a real MySQL server instead of the bundled SQLite file.
"""
import argparse
import sys
import threading
import webbrowser

from app import config, db, init_db, seed, server


def main():
    parser = argparse.ArgumentParser(description="Run the Smart Restock AI chatbot")
    parser.add_argument("--reset", action="store_true", help="rebuild the demo data")
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    print(f"\nSmart Restock AI — starting up ({config.DB_ENGINE})")
    try:
        init_db.create_schema()
        if args.reset:
            seed.reset_and_seed()
        elif init_db.is_empty():
            seed.seed_all()
        else:
            row = db.query("SELECT COUNT(*) AS n FROM products", fetchone=True)
            print(f"  existing data found ({row['n']} products) — run with --reset to rebuild")
    except Exception as exc:
        print(f"\n  Database setup failed: {exc}")
        if config.DB_ENGINE == "mysql":
            print("  Fix the MySQL settings in .env, or remove DB_ENGINE to use SQLite.")
        return 1

    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    try:
        server.serve(host=args.host, port=args.port)
    except KeyboardInterrupt:
        print("\n  stopped\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
