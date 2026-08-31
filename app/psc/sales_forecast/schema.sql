CREATE TABLE IF NOT EXISTS sales_forecast_line (
                version_no      TEXT    NOT NULL,
                material_no     TEXT    NOT NULL,
                customer_no     TEXT    NOT NULL,
                rolling_month   TEXT    NOT NULL,
                orig_qty        REAL,
                mape            REAL,
                bias            REAL,
                adj_qty         REAL,
                base_method     TEXT,
                base_params     TEXT,
                base_qty        REAL,
                event_analysis  TEXT,
                event_adj       REAL    NOT NULL DEFAULT 0,
                base_event_qty  REAL,
                bp_material_no  TEXT,
                switch_time     TEXT,
                abnormal_flag   INTEGER NOT NULL DEFAULT 0,
                final_qty       REAL,
                PRIMARY KEY (version_no, material_no, customer_no, rolling_month)
            );

CREATE TABLE IF NOT EXISTS sales_forecast_summary (
                version_no      TEXT    NOT NULL,
                material_no     TEXT    NOT NULL,
                rolling_month   TEXT    NOT NULL,
                final_qty_sum   REAL    NOT NULL DEFAULT 0,
                PRIMARY KEY (version_no, material_no, rolling_month)
            );

CREATE INDEX IF NOT EXISTS idx_sf_line_version ON sales_forecast_line (version_no);

CREATE INDEX IF NOT EXISTS idx_sf_line_material ON sales_forecast_line (material_no);

CREATE INDEX IF NOT EXISTS idx_sf_line_customer ON sales_forecast_line (customer_no);

CREATE INDEX IF NOT EXISTS idx_sf_line_abnormal ON sales_forecast_line (version_no, abnormal_flag);
