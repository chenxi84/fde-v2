from fde import FdeError


class SystemConfig:
    """系统配置——参数配置表 + 沉淀库（模板/类比/信任折扣）+ 外部数据源台账。"""

    def _init_db(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS param_config (
                param_code   TEXT PRIMARY KEY,
                param_name   TEXT NOT NULL,
                dimension    TEXT NOT NULL DEFAULT '全局',
                value        TEXT NOT NULL,
                default_value TEXT NOT NULL,
                eff_period   TEXT NOT NULL,
                calibration  TEXT,
                approver     TEXT
            );
            CREATE TABLE IF NOT EXISTS param_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                param_code  TEXT NOT NULL,
                old_value   TEXT NOT NULL,
                new_value   TEXT NOT NULL,
                changed_by  TEXT NOT NULL,
                changed_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                reason      TEXT
            );
            CREATE TABLE IF NOT EXISTS template_lib (
                tpl_no              TEXT PRIMARY KEY,
                shape_params        TEXT NOT NULL DEFAULT '{}',
                source_vehicle      TEXT,
                applicable_segment  TEXT,
                usage_count         INTEGER NOT NULL DEFAULT 0,
                fva_effect          TEXT
            );
            CREATE TABLE IF NOT EXISTS analogy_lib (
                ana_no           TEXT PRIMARY KEY,
                new_vehicle      TEXT NOT NULL,
                similar_vehicle  TEXT NOT NULL,
                basis            TEXT NOT NULL,
                history_effect   TEXT
            );
            CREATE TABLE IF NOT EXISTS trust_discount (
                oem_code       TEXT NOT NULL,
                part_no        TEXT,
                coefficient    REAL NOT NULL,
                direction      TEXT NOT NULL DEFAULT '扣减',
                source         TEXT NOT NULL DEFAULT 'D12自动',
                adjust_reason  TEXT,
                PRIMARY KEY (oem_code, part_no)
            );
            CREATE TABLE IF NOT EXISTS ext_data_source (
                src_no       TEXT PRIMARY KEY,
                data_cat     TEXT NOT NULL,
                channel      TEXT NOT NULL,
                caliber      TEXT NOT NULL,
                freq         TEXT NOT NULL,
                lag          TEXT NOT NULL,
                compliance   TEXT NOT NULL,
                mapping_ref  TEXT,
                consumers    TEXT NOT NULL,
                quality      TEXT NOT NULL DEFAULT '正常'
            );
        """)

    # ---- 参数配置 ----
    def get_param(self, param_code: str):
        row = self.db.execute("SELECT * FROM param_config WHERE param_code = ?", (param_code,)).fetchone()
        if not row:
            raise FdeError(f"参数 {param_code} 未配置")
        return dict(row)

    def list_params(self, dimension: str = None):
        sql = "SELECT * FROM param_config"
        params = []
        if dimension:
            sql += " WHERE dimension = ?"
            params.append(dimension)
        rows = self.db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def set_param(self, param_code: str, value: str, calibration: str, approver: str):
        old = self.db.execute("SELECT value FROM param_config WHERE param_code = ?", (param_code,)).fetchone()
        if not old:
            raise FdeError(f"参数 {param_code} 不存在，请先初始化")
        old_value = old["value"]
        if old_value == value:
            return {"param_code": param_code, "value": value, "changed": False}
        self.db.execute(
            "UPDATE param_config SET value = ?, calibration = ?, approver = ? WHERE param_code = ?",
            (value, calibration, approver, param_code)
        )
        self.db.execute(
            "INSERT INTO param_history (param_code, old_value, new_value, changed_by, reason) VALUES (?,?,?,?,?)",
            (param_code, old_value, value, approver, calibration)
        )
        return {"param_code": param_code, "value": value, "old_value": old_value, "changed": True}

    def _ensure_default_params(self):
        """确保预设参数存在（幂等）"""
        defaults = [
            ("θ_step", "阶跃判定阈值", "全局", "max(10%×期量, 50件)"),
            ("θ_noise", "尖峰判定阈值", "全局", "15%"),
            ("θ_baseline", "基线交叉偏差阈值", "全局", "15%"),
            ("θ_rev", "过度修正举证阈值", "全局", "20%"),
            ("θ_amp", "牛鞭容忍区间", "全局", "1.10"),
            ("θ_exo", "外生校验转人工阈值", "全局", "10%"),
            ("对账警戒线", "拆解vs结算偏差预警", "全局", "±8%"),
            ("考核容忍区间", "追责容忍", "全局", "±10%"),
            ("核对升级轮次", "D04升级阈值", "全局", "2"),
        ]
        for code, name, dim, val in defaults:
            self.db.execute(
                "INSERT OR IGNORE INTO param_config (param_code, param_name, dimension, value, default_value, eff_period) VALUES (?,?,?,?,?,?)",
                (code, name, dim, val, val, "2026Q3")
            )

    # ---- 模板库 ----
    def list_templates(self):
        rows = self.db.execute("SELECT * FROM template_lib ORDER BY usage_count DESC").fetchall()
        return [dict(r) for r in rows]

    def get_template(self, tpl_no: str):
        row = self.db.execute("SELECT * FROM template_lib WHERE tpl_no = ?", (tpl_no,)).fetchone()
        if not row:
            raise FdeError(f"模板 {tpl_no} 不存在")
        return dict(row)

    def create_template(self, tpl_no: str, shape_params: str, source_vehicle: str = None, applicable_segment: str = None):
        existing = self.db.execute("SELECT 1 FROM template_lib WHERE tpl_no = ?", (tpl_no,)).fetchone()
        if existing:
            raise FdeError(f"模板 {tpl_no} 已存在")
        self.db.execute(
            "INSERT INTO template_lib (tpl_no, shape_params, source_vehicle, applicable_segment) VALUES (?,?,?,?)",
            (tpl_no, shape_params, source_vehicle, applicable_segment)
        )
        return {"tpl_no": tpl_no}

    # ---- 类比库 ----
    def list_analogies(self):
        rows = self.db.execute("SELECT * FROM analogy_lib").fetchall()
        return [dict(r) for r in rows]

    def create_analogy(self, ana_no: str, new_vehicle: str, similar_vehicle: str, basis: str):
        self.db.execute(
            "INSERT INTO analogy_lib (ana_no, new_vehicle, similar_vehicle, basis) VALUES (?,?,?,?)",
            (ana_no, new_vehicle, similar_vehicle, basis)
        )
        return {"ana_no": ana_no}

    # ---- 信任折扣 ----
    def get_trust_discount(self, oem_code: str, part_no: str = None):
        key_part = part_no if part_no else ""
        row = self.db.execute(
            "SELECT * FROM trust_discount WHERE oem_code = ? AND (part_no = ? OR part_no IS NULL) ORDER BY part_no DESC LIMIT 1",
            (oem_code, key_part)
        ).fetchone()
        if not row:
            return {"oem_code": oem_code, "coefficient": 1.0, "direction": "直采", "source": "默认"}
        return dict(row)

    def update_trust_discount(self, oem_code: str, coefficient: float, direction: str, basis: str = None, part_no: str = None):
        self.db.execute(
            "INSERT OR REPLACE INTO trust_discount (oem_code, part_no, coefficient, direction, source, adjust_reason) VALUES (?,?,?,?,?,?)",
            (oem_code, part_no, coefficient, direction, "人工调整" if basis else "D12自动", basis)
        )
        return {"oem_code": oem_code, "coefficient": coefficient}

    # ---- 外部数据源台账 ----
    def list_ext_sources(self):
        rows = self.db.execute("SELECT * FROM ext_data_source").fetchall()
        return [dict(r) for r in rows]

    def register_ext_source(self, src_no: str, data_cat: str, channel: str, caliber: str,
                            freq: str, lag: str, compliance: str, consumers: str):
        self.db.execute(
            "INSERT INTO ext_data_source (src_no, data_cat, channel, caliber, freq, lag, compliance, consumers) VALUES (?,?,?,?,?,?,?,?)",
            (src_no, data_cat, channel, caliber, freq, lag, compliance, consumers)
        )
        return {"src_no": src_no}
