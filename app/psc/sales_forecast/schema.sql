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

-- 人工定稿台账（异常行的人工决策留痕）：**定过的行不再被 decide 覆盖**。
--
-- 为什么单独一张表而不是给 sales_forecast_line 加列：平台对应用库只做
-- `CREATE TABLE IF NOT EXISTS`（没有给已有表加列的机制），而 demo_reset 是清空行、
-- 不重建库文件——加列对已有库不生效，运行期会 no such column。
-- 新表用 IF NOT EXISTS，**对已有库也会自动建**，零迁移风险。
-- 顺带留下「谁在什么时候定的稿」，人工决策可追溯。
CREATE TABLE IF NOT EXISTS sales_forecast_settle (
                version_no      TEXT    NOT NULL,
                material_no     TEXT    NOT NULL,
                customer_no     TEXT    NOT NULL,
                rolling_month   TEXT    NOT NULL,
                final_qty       REAL    NOT NULL,
                settled_by      TEXT,
                settled_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
                PRIMARY KEY (version_no, material_no, customer_no, rolling_month)
);

CREATE INDEX IF NOT EXISTS idx_sf_settle_version ON sales_forecast_settle (version_no);
