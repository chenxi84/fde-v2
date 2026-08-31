CREATE TABLE IF NOT EXISTS master_plan (
                material_no         TEXT    NOT NULL,
                version_no          TEXT    NOT NULL,
                rolling_month       TEXT    NOT NULL CHECK (rolling_month IN ('N+1', 'N+2', 'N+3')),
                plan_version        INTEGER NOT NULL,
                plan_qty            REAL    NOT NULL,
                latest_inbound_date TEXT    NOT NULL,
                PRIMARY KEY (plan_version, material_no, rolling_month),
                UNIQUE (version_no, material_no, rolling_month, plan_version)
            );

CREATE INDEX IF NOT EXISTS idx_master_plan_version_material ON master_plan (version_no, material_no);

CREATE INDEX IF NOT EXISTS idx_master_plan_material_rolling ON master_plan (material_no, rolling_month);
