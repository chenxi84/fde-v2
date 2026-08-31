CREATE TABLE IF NOT EXISTS md_customer (
                customer_no        TEXT    NOT NULL PRIMARY KEY,
                customer_name      TEXT    NOT NULL,
                credit_code        TEXT,
                settle_mode        TEXT    CHECK (settle_mode IS NULL OR settle_mode IN ('现售', '寄售')),
                line_stock_days    INTEGER NOT NULL DEFAULT 0,
                transfer_lead_days INTEGER
            );
