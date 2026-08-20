from fde import FdeError


class BullwhipCorrection:
    """牛鞭修正处理表——发布前最后一道口径修正。
    派生需求→终端口径锚定。Tier1直供简化确认；Tier2/3强制执行修正分析。
    """

    def _init_db(self):
        self.db.execute("""CREATE TABLE IF NOT EXISTS d08 (
                bw_no        TEXT PRIMARY KEY,
                part_no      TEXT NOT NULL,
                period       TEXT NOT NULL,
                tier         TEXT NOT NULL,
                derived_qty  REAL NOT NULL,
                end_qty      REAL NOT NULL,
                end_source   TEXT NOT NULL,
                amp_factor   REAL NOT NULL,
                amp_verdict  TEXT NOT NULL,
                corr_action  TEXT,
                final_qty    REAL NOT NULL,
                checker      TEXT,
                chk_date     TEXT,
                status       TEXT NOT NULL DEFAULT '待处理'
            );""")

    def create(self, part_no: str, period: str, tier: str, derived_qty: float = None,
               end_qty: float = None, end_source: str = "结算"):
        """新建处理单。系统自动计算放大系数。"""
        from datetime import datetime
        now = datetime.now().strftime("%Y%m%d%H%M%S%f")
        bw_no = f"BW-{now[:6]}-{now[6:]}"
        # 尝试从 D04 取核定值作为派生需求
        if derived_qty is None:
            try:
                approved = self.fde.call("demand_processing", "get_approved", part_no=part_no, period=period)
                if approved and approved.get("items"):
                    derived_qty = sum(float(i.get("approved_qty", 0)) for i in approved["items"])
            except Exception:
                pass
        # 通用件场景：尝试从 D07 取修正总量
        try:
            agg = self.fde.call("common_parts_agg", "get", agg_no=f"AGG-{part_no}-{period}")
        except Exception:
            pass
        # 尝试取车型映射用于外部数据桥接
        try:
            mapping = self.fde.call("vehicle_part_map", "get_active_mapping", part_no=part_no)
        except Exception:
            pass
        if derived_qty is None or end_qty is None:
            raise FdeError("派生需求量和终端需求量均为必填")
        if end_qty == 0:
            raise FdeError("终端需求量不能为0")
        amp_factor = derived_qty / end_qty
        # 获取θ_amp参数
        theta_amp = 1.10
        try:
            param = self.fde.call("system_config", "get_param", param_code="θ_amp")
            theta_amp = float(param.get("value", "1.10"))
        except Exception:
            pass
        amp_verdict = "容忍内·维持" if amp_factor <= theta_amp else "超阈·修正"
        # 待处理 → 由 maintain / set_correction 驱动状态流转
        status = "待处理"
        final_qty = derived_qty
        corr_action = "维持——放大已由拆解先行完成" if (tier == "Tier1直供" and amp_factor <= theta_amp) else None
        if amp_verdict == "超阈·修正":
            final_qty = end_qty  # 初始=终端需求，待人工修正
            status = "待处理"
            corr_action = None
        self.db.execute(
            """INSERT INTO d08 (bw_no, part_no, period, tier, derived_qty, end_qty,
               end_source, amp_factor, amp_verdict, corr_action, final_qty, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (bw_no, part_no, period, tier, derived_qty, end_qty,
             end_source, amp_factor, amp_verdict, corr_action, final_qty, status)
        )
        return {"bw_no": bw_no, "amp_factor": round(amp_factor, 4), "amp_verdict": amp_verdict, "status": status}

    def get(self, bw_no: str):
        row = self._get_row(bw_no)
        return dict(row)

    def list(self, part_no: str = None, period: str = None, tier: str = None, status: str = None, page: int = None, size: int = None):
        sql = "SELECT * FROM d08 WHERE 1=1"
        params = []
        if part_no:
            sql += " AND part_no=?"
            params.append(part_no)
        if period:
            sql += " AND period=?"
            params.append(period)
        if tier:
            sql += " AND tier=?"
            params.append(tier)
        if status:
            sql += " AND status=?"
            params.append(status)
        rows = self.db.execute(sql, params).fetchall()
        total = len(rows)
        # 服务端分页
        if page is not None and size is not None:
            page_no = max(1, int(page) if page else 1)
            size_n = max(1, int(size) if size else 50)
            start = (page_no - 1) * size_n
            rows = rows[start:start + size_n]

        return {"items": [dict(r) for r in rows], "total": total}

    def set_correction(self, bw_no: str, corr_action: str, final_qty: float):
        """执行修正（超阈场景）"""
        row = self._get_row(bw_no)
        if row["amp_verdict"] != "超阈·修正":
            raise FdeError("仅超阈处理单可执行修正")
        if not corr_action or not corr_action.strip():
            raise FdeError("修正必须登记所落机制与依据，禁止无机制纯减数")
        self.db.execute(
            "UPDATE d08 SET corr_action=?, final_qty=?, status='已修正', checker=?, chk_date=date('now') WHERE bw_no=?",
            (corr_action, final_qty, self.ctx["userno"], bw_no)
        )
        return {"bw_no": bw_no, "status": "已修正", "final_qty": final_qty}

    def maintain(self, bw_no: str):
        """容忍内维持：待处理 + 容忍内 → 维持"""
        row = self._get_row(bw_no)
        if row["status"] != "待处理":
            raise FdeError(f"当前状态 {row['status']}，仅待处理状态可维持")
        self.db.execute(
            "UPDATE d08 SET status='维持', checker=?, chk_date=date('now') WHERE bw_no=?",
            (self.ctx["userno"], bw_no)
        )
        return {"bw_no": bw_no, "status": "维持"}

    def confirm(self, bw_no: str):
        """确认：维持/已修正 → 已确认，转入发布"""
        row = self._get_row(bw_no)
        if row["status"] not in ("维持", "已修正"):
            raise FdeError(f"当前状态 {row['status']}，仅维持/已修正状态可确认")
        self.db.execute(
            "UPDATE d08 SET status='已确认', checker=?, chk_date=date('now') WHERE bw_no=?",
            (self.ctx["userno"], bw_no)
        )
        return {"bw_no": bw_no, "status": "已确认"}

    def _get_row(self, bw_no: str):
        row = self.db.execute("SELECT * FROM d08 WHERE bw_no=?", (bw_no,)).fetchone()
        if not row:
            raise FdeError(f"牛鞭处理单 {bw_no} 不存在")
        return row
