CREATE TABLE IF NOT EXISTS demand (
                version_no      TEXT    NOT NULL,
                material_no     TEXT    NOT NULL,
                rolling_month   TEXT    NOT NULL,
                forecast_qty    REAL    NOT NULL DEFAULT 0,
                inventory_qty   REAL    NOT NULL DEFAULT 0,
                gross_qty       REAL    NOT NULL DEFAULT 0,
                open_order_qty  REAL    NOT NULL DEFAULT 0,
                onhand_qty      REAL    NOT NULL DEFAULT 0,
                in_transit_qty  REAL    NOT NULL DEFAULT 0,
                net_qty         REAL    NOT NULL DEFAULT 0,
                PRIMARY KEY (version_no, material_no, rolling_month)
            );

CREATE INDEX IF NOT EXISTS idx_demand_material_no ON demand (material_no);
