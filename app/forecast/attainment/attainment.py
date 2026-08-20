from fde import FdeError


class Attainment:
    """达成率与置信度聚合根。月度闭环自动生成客户预测达成率与置信系数，供下期加工表置信度调整使用。
    数据来源类型：自动参考创建——由月度闭环 compute_batch 触发，前端禁止创建入口。"""

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS attainment (
                oem_code TEXT NOT NULL,
                period TEXT NOT NULL,
                horizon TEXT NOT NULL CHECK (horizon IN ('H1', 'H2', 'H3')),
                snap_qty REAL NOT NULL DEFAULT 0,
                settle_qty REAL NOT NULL DEFAULT 0,
                attain_rate REAL NOT NULL DEFAULT 0,
                conf_factor REAL NOT NULL DEFAULT 1.0,
                gen_batch TEXT DEFAULT '',
                PRIMARY KEY (oem_code, period, horizon)
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_attainment_oem ON attainment (oem_code)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_attainment_period ON attainment (period)")

    def compute(self, oem_code: str, period: str):
        """按月+客户计算达成率与置信系数"""
        oem_code = self._clean(oem_code)
        period = self._clean(period)
        if not oem_code:
            raise FdeError("客户编码必填")
        if not period:
            raise FdeError("期间必填")

        # 取三个 horizon 的快照量（H1=当期M+1预测, H2=上月M+2预测, H3=前两月M+3预测逻辑简化：按 horizon 查询快照）
        horizons = ["H1", "H2", "H3"]
        results = []
        for h in horizons:
            # 取快照原始量（从 forecast_snapshot 按客户+期间查询，简化处理）
            try:
                snap_list = self.fde.call("forecast_snapshot", "list",
                    oem_code=oem_code, period=period, page=1, page_size=100)
                snap_qty = sum(float(item.get("orig_qty", 0) or 0) for item in snap_list.get("items", []))
            except FdeError:
                snap_qty = 0

            # 取结算实际量（从 ERP H1/H2 通过适配器获取）
            settle_qty = self._load_settlement(oem_code, period)

            # 计算达成率（一次性调整量不混入——在快照侧已排除）
            if snap_qty > 0:
                attain_rate = round(settle_qty / snap_qty, 4)
            else:
                attain_rate = 0

            # 置信系数：近3期达成率滚动值，截断[0.8, 1.2]
            conf_factor = self._calc_conf_factor(oem_code, period)

            self.db.execute("""
                INSERT OR REPLACE INTO attainment (oem_code, period, horizon, snap_qty, settle_qty, attain_rate, conf_factor, gen_batch)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (oem_code, period, h, snap_qty, settle_qty, attain_rate, conf_factor, period))

            results.append({"oem_code": oem_code, "period": period, "horizon": h,
                           "snap_qty": snap_qty, "settle_qty": settle_qty,
                           "attain_rate": attain_rate, "conf_factor": conf_factor})

        return results

    def compute_batch(self, fcst_version: str):
        """批量计算（月度闭环触发）：对全部客户计算最新期间的达成率"""
        fcst_version = self._clean(fcst_version)
        if not fcst_version:
            raise FdeError("版本号必填")
        # 取活跃快照版本的全部客户
        try:
            snap_list = self.fde.call("forecast_snapshot", "list", fcst_version=fcst_version, page=1, page_size=10000)
        except FdeError as e:
            raise FdeError(f"取快照数据失败: {e}") from None
        # 按客户去重
        oem_codes = list(set(item.get("oem_code", "") for item in snap_list.get("items", []) if item.get("oem_code")))
        # 取版本对应期间（简化：用第一个快照行的期间）
        periods_set = set(item.get("period", "") for item in snap_list.get("items", []) if item.get("period"))
        results = []
        for oem_code in oem_codes:
            for period in sorted(periods_set):
                try:
                    r = self.compute(oem_code, period)
                    results.extend(r)
                except FdeError:
                    continue
        return {"computed": len(results), "oem_count": len(oem_codes)}

    def get(self, oem_code: str, period: str):
        oem_code = self._clean(oem_code)
        period = self._clean(period)
        if not oem_code or not period:
            raise FdeError("客户编码和期间必填")
        rows = self.db.execute(
            "SELECT oem_code, period, horizon, snap_qty, settle_qty, attain_rate, conf_factor, gen_batch FROM attainment WHERE oem_code = ? AND period = ? ORDER BY horizon",
            (oem_code, period),
        ).fetchall()
        if not rows:
            raise FdeError(f"客户 {oem_code} 期间 {period} 的达成率数据不存在")
        return [dict(r) for r in rows]

    def list(self, oem_code: str = None, period: str = None, horizon: str = None, page: int = None, page_size: int = None):
        oem_code = self._clean(oem_code)
        period = self._clean(period)
        horizon = self._clean(horizon)
        sql = "SELECT oem_code, period, horizon, snap_qty, settle_qty, attain_rate, conf_factor, gen_batch FROM attainment"
        clauses, params = [], []
        if oem_code:
            clauses.append("oem_code LIKE '%' || ? || '%'")
            params.append(oem_code)
        if period:
            clauses.append("period = ?")
            params.append(period)
        if horizon:
            if horizon not in ("H1", "H2", "H3"):
                raise FdeError("horizon 只能为 H1/H2/H3")
            clauses.append("horizon = ?")
            params.append(horizon)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY oem_code, period, horizon"
        rows = self.db.execute(sql, tuple(params)).fetchall()
        items = [dict(r) for r in rows]
        total = len(items)
        if page is None and page_size is None:
            return {"total": total, "items": items}
        page_no = self._to_int(page, 1)
        page_sz = self._to_int(page_size, 50)
        if page_no < 1:
            page_no = 1
        if page_sz < 1:
            page_sz = 50
        start = (page_no - 1) * page_sz
        return {"total": total, "items": items[start:start + page_sz]}

    def get_conf_factor(self, oem_code: str, period: str):
        """取置信系数（供加工表使用），默认 1.0"""
        oem_code = self._clean(oem_code)
        period = self._clean(period)
        if not oem_code or not period:
            return 1.0
        rows = self.db.execute(
            "SELECT conf_factor FROM attainment WHERE oem_code = ? AND period = ? ORDER BY horizon",
            (oem_code, period),
        ).fetchall()
        if not rows:
            return 1.0
        factors = [r["conf_factor"] for r in rows]
        return round(sum(factors) / len(factors), 4) if factors else 1.0

    def _calc_conf_factor(self, oem_code, period):
        """近3期达成率滚动值，截断[0.8, 1.2]"""
        rows = self.db.execute(
            "SELECT attain_rate FROM attainment WHERE oem_code = ? AND period <= ? ORDER BY period DESC LIMIT 3",
            (oem_code, period),
        ).fetchall()
        if not rows:
            return 1.0
        rates = [r["attain_rate"] for r in rows if r["attain_rate"] > 0]
        if not rates:
            return 1.0
        avg = sum(rates) / len(rates)
        if avg >= 0.95:
            return 1.0
        clamped = max(0.8, min(1.2, avg))
        return round(clamped, 2)

    def _load_settlement(self, oem_code, period):
        """从 ERP H1/H2 适配器加载结算实际量（V1 stub 返回 0）"""
        try:
            cust = self.fde.call("md_customer", "get", oem_code=oem_code, plant_code="")
        except FdeError:
            return 0
        # V1 stub: 寄售客户默认返回快照量的 95%（模拟高达成率），非寄售返回 0
        if cust.get("settle_mode") == "寄售":
            try:
                snap_list = self.fde.call("forecast_snapshot", "list", oem_code=oem_code, period=period, page=1, page_size=100)
                snap_qty = sum(float(item.get("orig_qty", 0) or 0) for item in snap_list.get("items", []))
                return round(snap_qty * 0.95, 2) if snap_qty > 0 else 0
            except FdeError:
                return 0
        return 0

    def _clean(self, value):
        if value is None:
            return ""
        return str(value).strip()

    def _to_int(self, value, default):
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            raise FdeError("分页参数非法")
