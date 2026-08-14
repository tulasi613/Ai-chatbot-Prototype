"""
Schema definition, expressed once per engine.

`database/schema_mysql.sql` is the canonical MySQL DDL (identical to the
statements below); the SQLite variant exists purely so the demo can run
without a database server. Column names, types and relationships match
one-for-one, so application SQL is engine independent.
"""

MYSQL_DDL = [
    """CREATE TABLE IF NOT EXISTS suppliers (
        supplier_id         INT AUTO_INCREMENT PRIMARY KEY,
        supplier_name       VARCHAR(150) NOT NULL,
        avg_lead_time_days  INT NOT NULL DEFAULT 7,
        reliability_score   DECIMAL(5,2) NOT NULL DEFAULT 90.00,
        last_delivery_date  DATE NULL,
        contact_email       VARCHAR(150),
        created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS products (
        product_id        INT AUTO_INCREMENT PRIMARY KEY,
        name              VARCHAR(150) NOT NULL,
        category          VARCHAR(80)  NOT NULL,
        price             DECIMAL(10,2) NOT NULL,
        stock_level       INT NOT NULL DEFAULT 0,
        attributes        JSON NULL,
        image_url         VARCHAR(255),
        supplier_id       INT,
        reorder_threshold INT NOT NULL DEFAULT 5,
        created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_product_supplier FOREIGN KEY (supplier_id)
            REFERENCES suppliers(supplier_id) ON DELETE SET NULL,
        INDEX idx_category (category),
        INDEX idx_stock (stock_level)
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS sales_log (
        sale_id       INT AUTO_INCREMENT PRIMARY KEY,
        product_id    INT NOT NULL,
        sale_date     DATE NOT NULL,
        quantity_sold INT NOT NULL,
        unit_price    DECIMAL(10,2) NOT NULL,
        CONSTRAINT fk_sales_product FOREIGN KEY (product_id)
            REFERENCES products(product_id) ON DELETE CASCADE,
        INDEX idx_sales_product_date (product_id, sale_date)
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS customer_subscriptions (
        subscription_id INT AUTO_INCREMENT PRIMARY KEY,
        product_id      INT NOT NULL,
        customer_email  VARCHAR(150),
        customer_phone  VARCHAR(30),
        subscribed_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        notified        BOOLEAN DEFAULT FALSE,
        notified_at     TIMESTAMP NULL,
        CONSTRAINT fk_sub_product FOREIGN KEY (product_id)
            REFERENCES products(product_id) ON DELETE CASCADE,
        INDEX idx_sub_product (product_id)
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS chatbot_query_log (
        query_id   INT AUTO_INCREMENT PRIMARY KEY,
        product_id INT NOT NULL,
        query_type VARCHAR(50) NOT NULL,
        query_text VARCHAR(255),
        queried_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_query_product FOREIGN KEY (product_id)
            REFERENCES products(product_id) ON DELETE CASCADE,
        INDEX idx_query_product (product_id)
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS admin_demand_alerts (
        alert_id       INT AUTO_INCREMENT PRIMARY KEY,
        product_id     INT NOT NULL,
        alert_type     VARCHAR(50) NOT NULL,
        interest_count INT DEFAULT 0,
        alert_message  VARCHAR(255),
        created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_resolved    BOOLEAN DEFAULT FALSE,
        CONSTRAINT fk_alert_product FOREIGN KEY (product_id)
            REFERENCES products(product_id) ON DELETE CASCADE,
        INDEX idx_alert_product (product_id)
    ) ENGINE=InnoDB""",
]

SQLITE_DDL = [
    """CREATE TABLE IF NOT EXISTS suppliers (
        supplier_id         INTEGER PRIMARY KEY AUTOINCREMENT,
        supplier_name       TEXT NOT NULL,
        avg_lead_time_days  INTEGER NOT NULL DEFAULT 7,
        reliability_score   REAL NOT NULL DEFAULT 90.00,
        last_delivery_date  TEXT,
        contact_email       TEXT,
        created_at          TEXT DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS products (
        product_id        INTEGER PRIMARY KEY AUTOINCREMENT,
        name              TEXT NOT NULL,
        category          TEXT NOT NULL,
        price             REAL NOT NULL,
        stock_level       INTEGER NOT NULL DEFAULT 0,
        attributes        TEXT,
        image_url         TEXT,
        supplier_id       INTEGER REFERENCES suppliers(supplier_id) ON DELETE SET NULL,
        reorder_threshold INTEGER NOT NULL DEFAULT 5,
        created_at        TEXT DEFAULT CURRENT_TIMESTAMP
    )""",
    "CREATE INDEX IF NOT EXISTS idx_category ON products(category)",
    "CREATE INDEX IF NOT EXISTS idx_stock ON products(stock_level)",
    """CREATE TABLE IF NOT EXISTS sales_log (
        sale_id       INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id    INTEGER NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
        sale_date     TEXT NOT NULL,
        quantity_sold INTEGER NOT NULL,
        unit_price    REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_sales_product_date ON sales_log(product_id, sale_date)",
    """CREATE TABLE IF NOT EXISTS customer_subscriptions (
        subscription_id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id      INTEGER NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
        customer_email  TEXT,
        customer_phone  TEXT,
        subscribed_at   TEXT DEFAULT CURRENT_TIMESTAMP,
        notified        INTEGER DEFAULT 0,
        notified_at     TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_sub_product ON customer_subscriptions(product_id)",
    """CREATE TABLE IF NOT EXISTS chatbot_query_log (
        query_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
        query_type TEXT NOT NULL,
        query_text TEXT,
        queried_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""",
    "CREATE INDEX IF NOT EXISTS idx_query_product ON chatbot_query_log(product_id)",
    """CREATE TABLE IF NOT EXISTS admin_demand_alerts (
        alert_id       INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id     INTEGER NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
        alert_type     TEXT NOT NULL,
        interest_count INTEGER DEFAULT 0,
        alert_message  TEXT,
        created_at     TEXT DEFAULT CURRENT_TIMESTAMP,
        is_resolved    INTEGER DEFAULT 0
    )""",
    "CREATE INDEX IF NOT EXISTS idx_alert_product ON admin_demand_alerts(product_id)",
]

TABLES = [
    "admin_demand_alerts",
    "chatbot_query_log",
    "customer_subscriptions",
    "sales_log",
    "products",
    "suppliers",
]
