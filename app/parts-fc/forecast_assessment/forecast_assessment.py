from fde import FdeError


class ForecastAssessment:
    """预测转单率考核表——事后闭环。双口径：消耗口径评预测能力，发运口径评报数质量。"""

    def _init_db(self):
        self.db.execute("""CREATE TABLE IF NOT EXISTS d12 (
                fa_no        TEXT PRIMARY KEY,
                part_no      TEXT NOT NULL,
                veh_model    TEXT NOT NULL,
                period       TEXT NOT NULL,
                fcst_qty     REAL NOT NULL,
                actual_qty   REAL NOT NULL,
                conv_rate    REAL,
                dev_qty      REAL,
                settle_qty   REAL,
                base_qty     REAL,
                adj_qty      REAL,
                attribution  TEXT,
                result       TEXT,
                cycle        TEXT NOT NULL,
                assessor     TEXT
            );""")
        try:
            self.db.execute("ALTER TABLE d12 ADD COLUMN status TEXT NOT NULL DEFAULT '待归因'")
        except Exception:
            pass  # column already exists

    def create(self, period: str):
        """创建考核期批次。从D09取发布快照计算指标。"""
        from datetime import datetime
        now = datetime.now().strftime("%Y%m%d%H%M%S%f")
        fa_no = f"FA-{now[:6]}-{now[6:]}"
        self.db.execute(
            "INSERT INTO d12 (fa_no, part_no, veh_model, period, fcst_qty, actual_qty, settle_qty, base_qty, adj_qty, cycle, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (fa_no, "", "", period, 0, 0, 0, 0, 0, period, "待归因")
        )
        return {"fa_no": fa_no, "period": period, "note": "请逐个零件调用 add_record 填充考核记录"}

    def add_record(self, fa_no: str, part_no: str, veh_model: str, period: str,
                   fcst_qty: float, actual_qty: float, settle_qty: float,
                   base_qty: float, adj_qty: float):
        """添加单零件考核记录并自动计算指标"""
        conv_rate = actual_qty / max(abs(fcst_qty), 0.01) if fcst_qty else 0
        dev_qty = actual_qty - fcst_qty
        self.db.execute(
            """INSERT OR REPLACE INTO d12 (fa_no, part_no, veh_model, period, fcst_qty, actual_qty,
               conv_rate, dev_qty, settle_qty, base_qty, adj_qty, cycle, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fa_no, part_no, veh_model, period, fcst_qty, actual_qty, conv_rate, dev_qty,
             settle_qty, base_qty, adj_qty, period, "待归因")
        )
        return {"fa_no": fa_no, "part_no": part_no, "conv_rate": round(conv_rate, 4), "dev_qty": dev_qty}

    def calculate(self, period: str):
        """批量计算考核期指标（从D09/D04取快照）"""
        records = self.db.execute(
            "SELECT * FROM d12 WHERE cycle=? AND part_no!=''", (period,)
        ).fetchall()
        results = []
        for r in records:
            conv_rate = r["actual_qty"] / max(abs(r["fcst_qty"]), 0.01) if r["fcst_qty"] else 0
            dev_qty = r["actual_qty"] - r["fcst_qty"]
            self.db.execute(
                "UPDATE d12 SET conv_rate=?, dev_qty=?, status='已归档' WHERE fa_no=? AND part_no=? AND period=?",
                (conv_rate, dev_qty, r["fa_no"], r["part_no"], r["period"])
            )
            results.append({"part_no": r["part_no"], "conv_rate": round(conv_rate, 4), "dev_qty": dev_qty})
        return {"period": period, "records": len(results), "results": results}

    def attribute(self, fa_no: str, part_no: str, period: str, attribution: str, result: str, evidence: str = ""):
        """归因认定"""
        if result not in ("计入考核", "免责剔除", "归因流程·策略"):
            raise FdeError("考核结论必须为：计入考核/免责剔除/归因流程·策略")
        if result == "免责剔除" and not evidence.strip():
            raise FdeError("免责剔除须附举证（外部减产信息/销量骤降/结算趋势/客户函件）")
        self.db.execute(
            "UPDATE d12 SET attribution=?, result=?, status='已归档', assessor=? WHERE fa_no=? AND part_no=? AND period=?",
            (f"{attribution}|{evidence}", result, self.ctx["userno"], fa_no, part_no, period)
        )
        return {"fa_no": fa_no, "part_no": part_no, "result": result}

    def get(self, fa_no: str):
        row = self.db.execute("SELECT * FROM d12 WHERE fa_no=?", (fa_no,)).fetchone()
        if not row:
            raise FdeError(f"考核单 {fa_no} 不存在")
        return dict(row)

    def list(self, part_no: str = None, period: str = None, result: str = None, page: int = None, size: int = None):
        sql = "SELECT * FROM d12 WHERE part_no!=''"
        params = []
        if part_no:
            sql += " AND part_no=?"
            params.append(part_no)
        if period:
            sql += " AND period=?"
            params.append(period)
        if result:
            sql += " AND result=?"
            params.append(result)
        rows = self.db.execute(sql, params).fetchall()
        total = len(rows)
        # 服务端分页
        if page is not None and size is not None:
            page_no = max(1, int(page) if page else 1)
            size_n = max(1, int(size) if size else 50)
            start = (page_no - 1) * size_n
            rows = rows[start:start + size_n]

        return {"items": [dict(r) for r in rows], "total": total}

    def get_fva_view(self, part_no: str, period: str):
        """FVA视图：基线误差 vs 核定误差"""
        records = self.db.execute(
            "SELECT * FROM d12 WHERE part_no=? AND period=?", (part_no, period)
        ).fetchall()
        result = []
        for r in records:
            base_err = abs(r["settle_qty"] - r["base_qty"]) if r["settle_qty"] and r["base_qty"] else 0
            adj_err = abs(r["settle_qty"] - r["adj_qty"]) if r["settle_qty"] and r["adj_qty"] else 0
            fva = base_err - adj_err
            result.append({"period": r["period"], "settle_qty": r["settle_qty"],
                           "base_qty": r["base_qty"], "base_error": base_err,
                           "adj_qty": r["adj_qty"], "adj_error": adj_err, "fva": fva})
        return result

    def get_trust_discount(self, oem_code: str):
        """供D04调用：返回客户信任折扣"""
        try:
            discount = self.fde.call("system_config", "get_trust_discount", oem_code=oem_code)
            return discount
        except Exception:
            return {"oem_code": oem_code, "coefficient": 1.0, "direction": "直采", "source": "默认"}
