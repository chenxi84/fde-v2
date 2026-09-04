CREATE TABLE IF NOT EXISTS md_material (
                material_no      TEXT PRIMARY KEY,
                material_name    TEXT NOT NULL,
                status           TEXT NOT NULL DEFAULT '正常',
                unit_value       REAL,
                value_class      TEXT,
                change_cost      REAL,
                prod_days        REAL,
                logistics_days   REAL,
                change_risk      TEXT,
                service_level    REAL,
                batch_window     REAL,
                base_method      TEXT,
                base_params      TEXT,
                fit_version      TEXT,
                fit_effective_at TIMESTAMP,
                model_blob       TEXT
            );

CREATE TABLE IF NOT EXISTS md_material_param_version (
                material_no   TEXT NOT NULL,
                fit_version   TEXT NOT NULL,
                base_method   TEXT,
                base_params   TEXT,
                batch_window  REAL,
                service_level REAL,
                effective_at  TIMESTAMP,
                model_blob    TEXT,
                PRIMARY KEY (material_no, fit_version)
            );

CREATE INDEX IF NOT EXISTS idx_md_material_status ON md_material (status);
