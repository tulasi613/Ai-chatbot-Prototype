"""
Create the schema and load the demo data.

    python -m app.init_db            # create if missing, seed if empty
    python -m app.init_db --reset    # wipe and re-seed

Works against whichever engine DB_ENGINE selects (sqlite by default, mysql when
configured in .env).
"""
import argparse
import sys

from . import config, db, schema, seed


def create_schema(verbose=True):
    if config.DB_ENGINE == "mysql":
        import mysql.connector

        cfg = dict(config.MYSQL_CONFIG)
        database = cfg.pop("database")
        conn = mysql.connector.connect(**cfg)
        cur = conn.cursor()
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{database}` "
            f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        cur.execute(f"USE `{database}`")
        for statement in schema.MYSQL_DDL:
            cur.execute(statement)
        conn.commit()
        cur.close()
        conn.close()
    else:
        conn = db.connect()
        for statement in schema.SQLITE_DDL:
            conn.execute(statement)
        conn.commit()
        conn.close()

    if verbose:
        print(f"  schema ready ({config.DB_ENGINE})")


def is_empty():
    row = db.query("SELECT COUNT(*) AS n FROM products", fetchone=True)
    return int(row["n"]) == 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Initialise the Restock AI database")
    parser.add_argument("--reset", action="store_true", help="wipe existing rows and re-seed")
    args = parser.parse_args(argv)

    print(f"\nInitialising {config.DB_ENGINE} database…")
    try:
        create_schema()
    except ModuleNotFoundError:
        print("\n  MySQL mode needs the connector:  pip install mysql-connector-python")
        print("  Or set DB_ENGINE=sqlite to run the zero-setup demo.\n")
        return 1
    except Exception as exc:
        print(f"\n  Could not create the schema: {exc}")
        if config.DB_ENGINE == "mysql":
            print("  Check that MySQL is running and DB_HOST/DB_USER/DB_PASSWORD in .env "
                  "are correct, or set DB_ENGINE=sqlite to run the zero-setup demo.")
        return 1

    if args.reset:
        seed.reset_and_seed()
    elif is_empty():
        seed.seed_all()
    else:
        print("  data already present — use --reset to rebuild")

    ok, target = db.ping()
    print(f"  database: {target}\n" if ok else f"  database unavailable: {target}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
