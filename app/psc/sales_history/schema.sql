CREATE TABLE IF NOT EXISTS sales_history (
                material_no  TEXT NOT NULL,
                customer_no  TEXT NOT NULL,
                period       TEXT NOT NULL,
                qty          REAL NOT NULL DEFAULT 0,
                forecast_qty REAL,
                PRIMARY KEY (material_no, customer_no, period)
            );

CREATE INDEX IF NOT EXISTS idx_sales_history_period ON sales_history (period);

CREATE INDEX IF NOT EXISTS idx_sales_history_customer ON sales_history (customer_no);
