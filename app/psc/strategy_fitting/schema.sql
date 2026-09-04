CREATE TABLE IF NOT EXISTS strategy_fitting (
                material_no     TEXT NOT NULL,
                fit_version     TEXT NOT NULL,
                pred_method     TEXT,
                pred_params     TEXT,
                smape           REAL,
                mase            REAL,
                pred_qty        REAL,
                pred_lo         REAL,
                pred_hi         REAL,
                detail_json     TEXT,
                service_factor  REAL,
                safety_level    REAL,
                batch_window    REAL,
                fulfill_rate    REAL,
                inv_days        REAL,
                changeover_cnt  INTEGER,
                abnormal_flag   INTEGER NOT NULL DEFAULT 0,
                status          TEXT NOT NULL DEFAULT '待复核'
                    CHECK (status IN ('待复核', '已生效', '已否决')),
                PRIMARY KEY (fit_version, material_no)
            );

CREATE INDEX IF NOT EXISTS idx_strategy_fitting_status ON strategy_fitting (status);

CREATE INDEX IF NOT EXISTS idx_strategy_fitting_material_no ON strategy_fitting (material_no);
