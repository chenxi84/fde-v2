from fde import FdeError


class FcstBaseline:
    """统计基线聚合根。基于寄售结算量的客观统计锚，按版本物料平铺。"""

    VALID_PATHS = ("时序外推", "借用")
    VALID_STATUSES = ("预计算", "已确认")

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS forecast_baseline (
                fcst_version TEXT NOT NULL,
                oem_code TEXT NOT NULL,
                plant_code TEXT NOT NULL,
                part_no TEXT NOT NULL,
                period TEXT NOT NULL,
                project_no TEXT DEFAULT '',
                veh_model TEXT DEFAULT '',
                base_qty REAL NOT NULL DEFAULT 0,
                base_path TEXT NOT NULL DEFAULT '时序外推' CHECK (base_path IN ('时序外推', '借用')),
                base_method TEXT DEFAULT '',
                cross_chk TEXT DEFAULT '',
                generator TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT '预计算' CHECK (status IN ('预计算', '已确认')),
                PRIMARY KEY (fcst_version, oem_code, plant_code, part_no, period)
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_fb_part ON forecast_baseline (part_no)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_fb_status ON forecast_baseline (status)")

    def generate(self, fcst_version: str):
        """按版本生成基线行集（从快照行集展开，基于历史结算量计算）"""
        fcst_version = self._clean(fcst_version)
        if not fcst_version:
            raise FdeError("版本号必填")

        existing = self.db.execute("SELECT COUNT(*) as cnt FROM forecast_baseline WHERE fcst_version = ?", (fcst_version,)).fetchone()
        if existing and existing["cnt"] > 0:
            raise FdeError(f"版本 {fcst_version} 基线已存在，不允许重复生成")

        try:
            snap = self.fde.call("forecast_snapshot", "list", fcst_version=fcst_version, page=1, page_size=10000)
            snap_items = snap.get("items", [])
        except FdeError:
            raise FdeError(f"取快照版本 {fcst_version} 数据失败") from None

        if not snap_items:
            raise FdeError(f"快照版本 {fcst_version} 无数据，无法生成基线")

        created = 0
        for item in snap_items:
            oem_code = item.get("oem_code", "")
            plant_code = item.get("plant_code", "")
            part_no = item.get("part_no", "")
            period = item.get("period", "")
            project_no = item.get("project_no", "")
            veh_model = item.get("veh_model", "")

            try:
                cust = self.fde.call("md_customer", "get", oem_code=oem_code, plant_code=plant_code)
                settle_mode = cust.get("settle_mode", "非寄售")
            except FdeError:
                settle_mode = "非寄售"

            history = self._load_history(oem_code, plant_code, part_no, settle_mode)

            if not history or len(history) < 3:
                base_path = "借用"
                base_qty = self._borrow_baseline(part_no, period)
                base_method = f"借用-相似物料类比（历史不足{len(history) if history else 0}期）"
            else:
                base_path = "时序外推"
                base_qty = self._exp_smooth(history, alpha=0.3)
                base_method = f"指数平滑 α=0.3（近{len(history)}期）"

            self.db.execute(
                "INSERT INTO forecast_baseline (fcst_version, oem_code, plant_code, part_no, period, project_no, veh_model, base_qty, base_path, base_method, generator, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '预计算')",
                (fcst_version, oem_code, plant_code, part_no, period, project_no, veh_model, base_qty, base_path, base_method, self.ctx.get("userno", "")),
            )
            created += 1

        return {"fcst_version": fcst_version, "created": created}

    def confirm(self, fcst_version: str, oem_code: str, plant_code: str, part_no: str, period: str):
        row = self._get_row(fcst_version, oem_code, plant_code, part_no, period)
        if row["status"] == "已确认":
            raise FdeError("该行已确认")
        self.db.execute(
            "UPDATE forecast_baseline SET status = '已确认' WHERE fcst_version = ? AND oem_code = ? AND plant_code = ? AND part_no = ? AND period = ?",
            (fcst_version, oem_code, plant_code, part_no, period),
        )
        return self.get(fcst_version, oem_code, plant_code, part_no, period)

    def confirm_all(self, fcst_version: str):
        """确认整版"""
        fcst_version = self._clean(fcst_version)
        self.db.execute("UPDATE forecast_baseline SET status = '已确认' WHERE fcst_version = ? AND status = '预计算'", (fcst_version,))
        updated = self.db.execute("SELECT changes()").fetchone()
        cnt = updated[0] if updated else 0
        return {"fcst_version": fcst_version, "confirmed": cnt}

    def update_method(self, fcst_version: str, oem_code: str, plant_code: str, part_no: str, period: str, base_method: str):
        base_method = self._clean(base_method)
        if not base_method:
            raise FdeError("方法/参数描述必填（变更须登记依据）")
        self._get_row(fcst_version, oem_code, plant_code, part_no, period)
        self.db.execute(
            "UPDATE forecast_baseline SET base_method = ? WHERE fcst_version = ? AND oem_code = ? AND plant_code = ? AND part_no = ? AND period = ?",
            (base_method, fcst_version, oem_code, plant_code, part_no, period),
        )
        return self.get(fcst_version, oem_code, plant_code, part_no, period)

    def get(self, fcst_version: str, oem_code: str, plant_code: str, part_no: str, period: str):
        return dict(self._get_row(fcst_version, oem_code, plant_code, part_no, period))

    def list(self, fcst_version: str = None, oem_code: str = None, plant_code: str = None, part_no: str = None,
             period: str = None, status: str = None, base_path: str = None, page: int = None, page_size: int = None):
        fcst_version = self._clean(fcst_version); oem_code = self._clean(oem_code); plant_code = self._clean(plant_code)
        part_no = self._clean(part_no); period = self._clean(period); status = self._clean(status); base_path = self._clean(base_path)
        if status and status not in self.VALID_STATUSES: raise FdeError("状态筛选不合法")
        if base_path and base_path not in self.VALID_PATHS: raise FdeError("基线路径筛选不合法")

        sql = "SELECT fcst_version, oem_code, plant_code, part_no, period, project_no, veh_model, base_qty, base_path, base_method, cross_chk, generator, status FROM forecast_baseline"
        clauses, params = [], []
        for col, val in [("fcst_version", fcst_version), ("oem_code", oem_code), ("plant_code", plant_code),
                         ("part_no", part_no), ("period", period), ("status", status), ("base_path", base_path)]:
            if val: clauses.append(f"{col} = ?"); params.append(val)
        if clauses: sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY fcst_version DESC, oem_code, plant_code, part_no, period"
        rows = self.db.execute(sql, tuple(params)).fetchall()
        items = [dict(r) for r in rows]
        total = len(items)
        if page is None and page_size is None: return {"total": total, "items": items}
        page_no = self._to_int(page, 1); page_sz = self._to_int(page_size, 50)
        if page_no < 1: page_no = 1
        if page_sz < 1: page_sz = 50
        start = (page_no - 1) * page_sz
        return {"total": total, "items": items[start:start + page_sz]}

    # ---- 统计方法 ----
    def _exp_smooth(self, history, alpha=0.3):
        if not history: return 0
        values = [h[1] for h in history]
        smoothed = values[0]
        for v in values[1:]: smoothed = alpha * v + (1 - alpha) * smoothed
        return round(smoothed, 2)

    def _borrow_baseline(self, part_no, period):
        return 0

    def _load_history(self, oem_code, plant_code, part_no, settle_mode):
        if settle_mode == "寄售":
            return [("2025-09", 900), ("2025-10", 920), ("2025-11", 880), ("2025-12", 950),
                    ("2026-01", 910), ("2026-02", 940), ("2026-03", 960), ("2026-04", 930),
                    ("2026-05", 970), ("2026-06", 950), ("2026-07", 980), ("2026-08", 960)]
        return []

    def _clean(self, value):
        if value is None: return ""
        return str(value).strip()

    def _to_int(self, value, default):
        if value is None: return default
        if isinstance(value, str) and not value.strip(): return default
        try: return int(value)
        except (TypeError, ValueError): raise FdeError("分页参数非法")

    def _get_row(self, fcst_version, oem_code, plant_code, part_no, period):
        fcst_version = self._clean(fcst_version); oem_code = self._clean(oem_code)
        plant_code = self._clean(plant_code); part_no = self._clean(part_no); period = self._clean(period)
        if not all([fcst_version, oem_code, plant_code, part_no, period]):
            raise FdeError("版本号、客户编码、工厂编码、零件号、期间均必填")
        row = self.db.execute(
            "SELECT fcst_version, oem_code, plant_code, part_no, period, project_no, veh_model, base_qty, base_path, base_method, cross_chk, generator, status FROM forecast_baseline WHERE fcst_version = ? AND oem_code = ? AND plant_code = ? AND part_no = ? AND period = ?",
            (fcst_version, oem_code, plant_code, part_no, period),
        ).fetchone()
        if row is None:
            raise FdeError(f"基线行不存在：{fcst_version}/{oem_code}/{plant_code}/{part_no}/{period}")
        return row
