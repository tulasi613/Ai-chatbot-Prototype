-- ============================================================
-- SMART RESTOCK AI - DATABASE SCHEMA (MySQL)
-- ============================================================
-- Run this with:
--   mysql -u root -p < schema.sql
-- ============================================================

DROP DATABASE IF EXISTS restock_ai;
CREATE DATABASE restock_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE restock_ai;

-- ------------------------------------------------------------
-- 1. SUPPLIERS & LEAD TIMES
-- ------------------------------------------------------------
CREATE TABLE suppliers (
    supplier_id        INT AUTO_INCREMENT PRIMARY KEY,
    supplier_name       VARCHAR(150) NOT NULL,
    avg_lead_time_days  INT NOT NULL DEFAULT 7,          -- average reorder lead time
    reliability_score   DECIMAL(5,2) NOT NULL DEFAULT 90.00, -- % of on-time historical deliveries
    last_delivery_date  DATE NULL,
    contact_email       VARCHAR(150),
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 2. PRODUCTS
-- ------------------------------------------------------------
CREATE TABLE products (
    product_id      INT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(150) NOT NULL,
    category        VARCHAR(80)  NOT NULL,
    price           DECIMAL(10,2) NOT NULL,
    stock_level     INT NOT NULL DEFAULT 0,
    attributes      JSON NULL,          -- e.g. {"color":"black","size":"M","material":"cotton"}
    image_url       VARCHAR(255),
    supplier_id     INT,
    reorder_threshold INT NOT NULL DEFAULT 5,  -- stock level admin wants to be warned at
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_product_supplier FOREIGN KEY (supplier_id)
        REFERENCES suppliers(supplier_id) ON DELETE SET NULL,
    INDEX idx_category (category),
    INDEX idx_stock (stock_level)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 3. SALES & INTEREST LOG
--    (split into 3 related tables for normalization, together
--    they form the "Sales & Interest Log" required by Task 1)
-- ------------------------------------------------------------

-- 3a. Historical sales
CREATE TABLE sales_log (
    sale_id         INT AUTO_INCREMENT PRIMARY KEY,
    product_id      INT NOT NULL,
    sale_date       DATE NOT NULL,
    quantity_sold   INT NOT NULL,
    unit_price      DECIMAL(10,2) NOT NULL,
    CONSTRAINT fk_sales_product FOREIGN KEY (product_id)
        REFERENCES products(product_id) ON DELETE CASCADE,
    INDEX idx_sales_product_date (product_id, sale_date)
) ENGINE=InnoDB;

-- 3b. Customer restock subscriptions ("notify me" requests)
CREATE TABLE customer_subscriptions (
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
) ENGINE=InnoDB;

-- 3c. Chatbot query counts (interest signal for out-of-stock / general queries)
CREATE TABLE chatbot_query_log (
    query_id    INT AUTO_INCREMENT PRIMARY KEY,
    product_id  INT NOT NULL,
    query_type  VARCHAR(50) NOT NULL,   -- 'availability' | 'alternative'
    query_text  VARCHAR(255),
    queried_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_query_product FOREIGN KEY (product_id)
        REFERENCES products(product_id) ON DELETE CASCADE,
    INDEX idx_query_product (product_id)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 4. ADMIN DEMAND ALERTS
--    Populated automatically when interest in an OOS item spikes,
--    or when fast sales velocity predicts an imminent stockout.
-- ------------------------------------------------------------
CREATE TABLE admin_demand_alerts (
    alert_id        INT AUTO_INCREMENT PRIMARY KEY,
    product_id      INT NOT NULL,
    alert_type      VARCHAR(50) NOT NULL,   -- 'high_interest_oos' | 'low_stock_predicted'
    interest_count  INT DEFAULT 0,
    alert_message   VARCHAR(255),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_resolved     BOOLEAN DEFAULT FALSE,
    CONSTRAINT fk_alert_product FOREIGN KEY (product_id)
        REFERENCES products(product_id) ON DELETE CASCADE,
    INDEX idx_alert_product (product_id)
) ENGINE=InnoDB;
