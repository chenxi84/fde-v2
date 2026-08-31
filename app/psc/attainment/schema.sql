CREATE TABLE IF NOT EXISTS attainment (
                customer_no TEXT NOT NULL,
                material_no TEXT NOT NULL,
                mape REAL,
                bias REAL,
                PRIMARY KEY (customer_no, material_no)
            );

CREATE INDEX IF NOT EXISTS idx_attainment_material_no ON attainment (material_no);
