CREATE TABLE IF NOT EXISTS outbound_plan (
                plan_no        TEXT PRIMARY KEY NOT NULL,
                customer_no    TEXT NOT NULL,
                material_no    TEXT NOT NULL,
                qty            REAL NOT NULL,
                out_date       TEXT NOT NULL,
                actual_out_no  TEXT,
                status         TEXT NOT NULL DEFAULT '待出库'
            );

CREATE INDEX IF NOT EXISTS idx_outbound_plan_material_no ON outbound_plan (material_no);

CREATE INDEX IF NOT EXISTS idx_outbound_plan_customer_no ON outbound_plan (customer_no);

CREATE INDEX IF NOT EXISTS idx_outbound_plan_status ON outbound_plan (status);

CREATE INDEX IF NOT EXISTS idx_outbound_plan_out_date ON outbound_plan (out_date);
