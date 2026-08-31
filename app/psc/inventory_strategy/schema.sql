CREATE TABLE IF NOT EXISTS inventory_strategy (
                version_no      TEXT NOT NULL,
                material_no     TEXT NOT NULL,
                hedge_tool      TEXT NOT NULL DEFAULT '库存' CHECK (hedge_tool IN ('库存', '速度')),
                min_level       REAL NOT NULL DEFAULT 0,
                service_factor  REAL NOT NULL DEFAULT 1.65,
                resp_volatility REAL NOT NULL DEFAULT 0,
                safety_level    REAL NOT NULL DEFAULT 0,
                batch_window    REAL NOT NULL DEFAULT 0,
                batch_level     REAL NOT NULL DEFAULT 0,
                basis           TEXT,
                PRIMARY KEY (version_no, material_no)
            );

CREATE INDEX IF NOT EXISTS idx_inventory_strategy_hedge_tool ON inventory_strategy (hedge_tool);

CREATE INDEX IF NOT EXISTS idx_inventory_strategy_material_no ON inventory_strategy (material_no);
