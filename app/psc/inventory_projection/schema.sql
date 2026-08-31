CREATE TABLE IF NOT EXISTS inventory_projection (
                material_no  TEXT NOT NULL,
                biz_date     TEXT NOT NULL,
                inbound_qty  REAL NOT NULL DEFAULT 0,
                outbound_qty REAL NOT NULL DEFAULT 0,
                balance      REAL NOT NULL DEFAULT 0,
                alert_type   TEXT NOT NULL DEFAULT '无',
                PRIMARY KEY (material_no, biz_date)
            );

CREATE INDEX IF NOT EXISTS idx_inventory_projection_biz_date ON inventory_projection (biz_date);

CREATE INDEX IF NOT EXISTS idx_inventory_projection_alert_type ON inventory_projection (alert_type);
