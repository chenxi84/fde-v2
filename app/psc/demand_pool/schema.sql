CREATE TABLE IF NOT EXISTS demand_pool (
                replenish_no      TEXT PRIMARY KEY NOT NULL,
                material_no       TEXT NOT NULL,
                replenish_type    TEXT NOT NULL,
                replenish_qty     REAL NOT NULL,
                required_inbound  TEXT NOT NULL,
                promised_inbound  TEXT,
                status            TEXT NOT NULL DEFAULT '待下达'
            );

CREATE INDEX IF NOT EXISTS idx_demand_pool_material_no ON demand_pool (material_no);

CREATE INDEX IF NOT EXISTS idx_demand_pool_replenish_type ON demand_pool (replenish_type);

CREATE INDEX IF NOT EXISTS idx_demand_pool_status ON demand_pool (status);
